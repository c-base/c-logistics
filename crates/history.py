"""History of the crates: who changed what, and older states to restore.

django-reversion stores the states. Every change made in the app records one
revision with the crate, its items and its photos, the member and a short note
on what happened. Restoring puts a crate back into such a state – only that
crate; other crates stay as they are.
"""
from contextlib import contextmanager
from dataclasses import dataclass, field

import reversion
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from reversion.models import Revision, Version

from members.models import Member

from .models import Crate, Item, Location, Photo, Tag

BASELINE_COMMENT = 'Ausgangsstand'
# What restoring sets on the crate itself; relations, items and photos come on top.
RESTORED_FIELDS = ('name', 'description', 'size', 'height_mm', 'color', 'needs_attention', 'attention_note')


def revisions_of(crate):
    """The recorded states of a crate, newest first."""
    return (
        Revision.objects.filter(
            version__content_type=ContentType.objects.get_for_model(Crate), version__object_id=str(crate.pk),
        )
        .select_related('user').order_by('-date_created', '-pk').distinct()
    )


def snapshot(user, comment, *crates):
    """Records the present state of the crates as one revision."""
    with reversion.create_revision():
        if user is not None and user.is_authenticated:
            reversion.set_user(user)
        reversion.set_comment(comment)
        for crate in Crate.objects.filter(pk__in=[crate.pk for crate in crates]):
            # every object explicitly, so that each is recorded as it is in the database now
            for entry in (crate, *crate.items.all(), *crate.photos.all()):
                reversion.add_to_revision(entry)


class _Change:
    """Handed to the block inside recording(); nothing() says that there is nothing to record after all."""

    happened = True

    def nothing(self):
        self.happened = False


@contextmanager
def recording(user, comment, *crates):
    """Around a change: afterwards the new state of the crates is in their history.

    A crate without history first gets its state before the change recorded;
    otherwise there would be nothing to go back to.
    """
    for crate in crates:
        if not Version.objects.get_for_object(crate).exists():
            snapshot(None, BASELINE_COMMENT, crate)
    change = _Change()
    with transaction.atomic():
        yield change
        if change.happened:
            snapshot(user, comment, *crates)


@dataclass
class PhotoEntry:
    image: str
    thumbnail: str
    uploaded_by_id: int
    created_at: object
    url: str
    thumbnail_url: str


@dataclass
class Contents:
    """A crate as it is now or as a revision recorded it – for showing side by side and for restoring."""

    crate: Crate  # unsaved copy when it comes from a revision
    location: object
    responsible: list
    tags: list
    items: list
    photos: list
    revision: object = None
    code: str = field(init=False)

    def __post_init__(self):
        self.code = self.crate.code

    def __getattr__(self, name):
        # name, description, size … are read from the crate
        if name == 'crate':
            raise AttributeError(name)
        return getattr(self.crate, name)

    @property
    def has_contents(self):
        return bool(self.items or self.photos)

    @classmethod
    def of(cls, crate):
        code = crate.code
        return cls(
            crate=crate, location=crate.location,
            responsible=list(crate.responsible.all()), tags=list(crate.tags.all()),
            items=list(crate.items.all()),
            photos=[
                PhotoEntry(
                    photo.image.name, photo.thumbnail.name, photo.uploaded_by_id, photo.created_at,
                    reverse('crates:photo', args=[code, photo.pk]),
                    reverse('crates:photo-thumbnail', args=[code, photo.pk]),
                )
                for photo in crate.photos.all()
            ],
        )

    @classmethod
    def from_revision(cls, crate, revision):
        """The crate as the revision recorded it, or None if the revision does not hold it."""
        recorded, items, photos = None, [], []
        for version in revision.version_set.select_related('content_type'):
            model, data = version.content_type.model_class(), version.field_dict
            if model is Crate and version.object_id == str(crate.pk):
                recorded = data
            elif model is Item and data.get('crate_id') == crate.pk:
                items.append(Item(name=data['name'], quantity=data['quantity'], note=data.get('note', '')))
            elif model is Photo and data.get('crate_id') == crate.pk:
                arguments = [crate.code, revision.pk, version.object_id]
                photos.append(PhotoEntry(
                    data['image'].name if hasattr(data['image'], 'name') else data['image'],
                    data['thumbnail'].name if hasattr(data['thumbnail'], 'name') else data['thumbnail'],
                    data.get('uploaded_by_id'), data.get('created_at'),
                    reverse('crates:revision-photo', args=arguments),
                    reverse('crates:revision-photo-thumbnail', args=arguments),
                ))
        if recorded is None:
            return None
        copy = Crate(code=crate.code, **{name: recorded[name] for name in RESTORED_FIELDS if name in recorded})
        # members, tags and locations that no longer exist drop out
        return cls(
            crate=copy,
            location=Location.objects.filter(pk=recorded.get('location_id')).first(),
            responsible=list(Member.objects.filter(pk__in=recorded.get('responsible', []))),
            tags=list(Tag.objects.filter(pk__in=recorded.get('tags', []))),
            items=sorted(items, key=lambda item: item.name),
            photos=sorted(photos, key=lambda photo: str(photo.created_at), reverse=True),
            revision=revision,
        )


def restore(crate, contents, user):
    """Puts the crate back into a recorded state. The state it had until now stays in the history."""
    when = date_format(timezone.localtime(contents.revision.date_created), 'SHORT_DATETIME_FORMAT')
    with recording(user, f'Stand vom {when} wiederhergestellt', crate):
        for name in RESTORED_FIELDS:
            setattr(crate, name, getattr(contents.crate, name))
        crate.location = contents.location
        crate.save()
        crate.responsible.set(contents.responsible or [Member.unknown()])
        crate.tags.set(contents.tags)

        crate.items.all().delete()
        Item.objects.bulk_create(
            Item(crate=crate, name=item.name, quantity=item.quantity, note=item.note) for item in contents.items
        )

        # Photos are told apart by their file. Deleting an entry leaves the files
        # alone, so a photo that is also shown in another crate stays intact there.
        wanted = {photo.image: photo for photo in contents.photos}
        for photo in crate.photos.all():
            if photo.image.name in wanted:
                del wanted[photo.image.name]
            else:
                photo.delete()
        members = set(Member.objects.filter(pk__in=[photo.uploaded_by_id for photo in wanted.values()]).values_list('pk', flat=True))
        storage = Photo._meta.get_field('image').storage
        for entry in wanted.values():
            if not storage.exists(entry.image):
                # the file has been cleared away in the meantime
                continue
            photo = Photo.objects.create(
                crate=crate, image=entry.image, thumbnail=entry.thumbnail,
                uploaded_by_id=entry.uploaded_by_id if entry.uploaded_by_id in members else None,
            )
            if entry.created_at:
                Photo.objects.filter(pk=photo.pk).update(created_at=entry.created_at)
