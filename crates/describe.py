"""Lässt die c-base-KI beschreiben, was auf einem Foto zu sehen ist.

Die Fotos gehen an ein Modell mit Bildverständnis hinter einer
OpenAI-kompatiblen Schnittstelle (`AI_BASE_URL`, z. B. Bonsai 2 unter
https://ai.cbrp3.c-base.org/bonsai/v1). Ohne `AI_BASE_URL` passiert nichts.
"""
import base64
import logging
import threading

import requests
from django.conf import settings
from django.db import connection

logger = logging.getLogger(__name__)

PROMPT = (
    'Das Foto zeigt den Inhalt einer Lagerkiste. Zähle auf Deutsch in ein bis drei '
    'kurzen Sätzen auf, welche Gegenstände zu sehen sind, und gib lesbare '
    'Beschriftungen wörtlich wieder. Nur Fließtext, keine Einleitung, keine Listen, '
    'kein Markdown. Beschreibe nicht den Hintergrund und rate nicht.'
)
# Reicht für drei Sätze; begrenzt die Wartezeit, falls das Modell abschweift.
MAX_TOKENS = 300


class DescribeError(Exception):
    """Die KI hat keine brauchbare Beschreibung geliefert."""


def enabled():
    return bool(settings.AI_BASE_URL)


def describe_image(jpeg):
    """Schickt ein JPEG (Bytes) an die KI und gibt die Beschreibung zurück."""
    picture = 'data:image/jpeg;base64,' + base64.b64encode(jpeg).decode('ascii')
    try:
        response = requests.post(
            f'{settings.AI_BASE_URL}/chat/completions',
            headers={'Authorization': f'Bearer {settings.AI_API_KEY}'} if settings.AI_API_KEY else {},
            json={
                'model': settings.AI_MODEL,
                # Bonsai denkt sonst erst nach; für eine Bildbeschreibung ist das unnötig.
                'reasoning_effort': 'none',
                'max_tokens': MAX_TOKENS,
                'messages': [{'role': 'user', 'content': [
                    {'type': 'text', 'text': PROMPT},
                    {'type': 'image_url', 'image_url': {'url': picture}},
                ]}],
            },
            timeout=settings.AI_TIMEOUT,
        )
        response.raise_for_status()
        text = response.json()['choices'][0]['message']['content']
    except (requests.RequestException, ValueError, LookupError, TypeError) as error:
        raise DescribeError(str(error)) from error
    text = ' '.join((text or '').split())
    if not text:
        raise DescribeError('leere Antwort')
    return text


def describe_photo(photo):
    """Beschreibt ein Foto und speichert den Text. Gibt zurück, ob es geklappt hat."""
    try:
        with photo.image.open('rb') as file:
            jpeg = file.read()
        description = describe_image(jpeg)
    except (DescribeError, OSError) as error:
        logger.warning('Foto %s ließ sich nicht beschreiben: %s', photo.pk, error)
        return False
    # Nur dieses Feld schreiben; das Foto kann inzwischen gelöscht sein.
    type(photo).objects.filter(pk=photo.pk).update(description=description)
    photo.description = description
    return True


def _describe_all(pks):
    from .models import Photo

    try:
        # Nacheinander: die KI nimmt nur zwei gleichzeitige Anfragen je Absender an.
        for photo in Photo.objects.filter(pk__in=pks, description=''):
            describe_photo(photo)
    except Exception:
        logger.exception('Beschreiben der Fotos %s abgebrochen', pks)
    finally:
        connection.close()


def describe_later(photos):
    """Beschreibt die Fotos im Hintergrund, damit der Upload nicht auf die KI wartet.

    Was dabei scheitert (KI nicht erreichbar, Neustart der App), holt
    `manage.py describe_photos` nach.
    """
    pks = [photo.pk for photo in photos]
    if pks and enabled():
        threading.Thread(target=_describe_all, args=(pks,), daemon=True).start()
