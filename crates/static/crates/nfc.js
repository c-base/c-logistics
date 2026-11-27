// Managers write the address of the crate onto an NFC tag and lock it – straight
// from the page, with Web NFC. That exists only in Chrome on Android, over HTTPS.
//
// The steps: write, read the tag back and compare, and only after that offer
// locking. Locking is final, so the tag is read and compared once more right
// before it, and the lock only gets a few seconds: a tag that has been taken
// away is not replaced by whichever tag comes next.
(function () {
  var box = document.getElementById('nfc-write');
  if (!box) return;
  if (!('NDEFReader' in window)) {
    document.getElementById('nfc-unsupported').hidden = false;
    return;
  }
  box.hidden = false;

  var url = box.dataset.url, lockable = box.dataset.lockable === '1';
  var writeButton = document.getElementById('nfc-write-button');
  var lockButton = document.getElementById('nfc-lock-button');
  var cancelButton = document.getElementById('nfc-cancel-button');
  var status = document.getElementById('nfc-status');
  var TAP_SECONDS = 30, LOCK_SECONDS = 10;
  var checked = null;   // {serial} of the tag that passed the check after writing
  var running = null;   // AbortController of the step in progress
  var timer = null;

  function say(text, kind) {
    status.textContent = text;
    status.className = 'nfc-status' + (kind ? ' ' + kind : '');
  }

  function begin() {
    running = new AbortController();
    writeButton.disabled = lockButton.disabled = true;
    cancelButton.hidden = false;
    return running.signal;
  }

  // The step fails with a timeout unless it is done within the given time.
  function limit(seconds) {
    clearTimeout(timer);
    var step = running;
    timer = setTimeout(function () { step.abort(); }, seconds * 1000);
  }

  function end() {
    clearTimeout(timer);
    // also stops reading
    if (running) running.abort();
    running = null;
    writeButton.disabled = lockButton.disabled = false;
    cancelButton.hidden = true;
  }

  function explain(error) {
    switch (error && error.name) {
      case 'AbortError': return 'Abgebrochen – es wurde kein Tag erkannt.';
      case 'NotAllowedError': return 'Der Browser darf NFC nicht benutzen. Bitte die Berechtigung für diese Seite erlauben.';
      case 'NotSupportedError': return 'NFC ist ausgeschaltet, oder der Tag lässt sich so nicht verwenden.';
      case 'NotReadableError': return 'NFC ist gerade nicht verfügbar. Ist es in den Einstellungen eingeschaltet?';
      case 'NetworkError': return 'Die Übertragung ist abgebrochen. Den Tag ruhig ans Telefon halten und noch einmal versuchen.';
      case 'InvalidStateError': return 'Es läuft schon ein Vorgang. Bitte noch einmal versuchen.';
      default: return 'Das hat nicht geklappt' + (error && error.message ? ': ' + error.message : '.');
    }
  }

  // The next tag held to the phone, as a reading event. onOther is called for every tag after it.
  function readTag(reader, signal, onOther) {
    return new Promise(function (resolve, reject) {
      var first = true;
      reader.onreading = function (event) {
        if (first) { first = false; resolve(event); } else if (onOther) { onOther(event); }
      };
      reader.onreadingerror = function () {
        if (first) reject(new DOMException('Der Tag lässt sich nicht lesen.', 'DataError'));
      };
      signal.addEventListener('abort', function () { reject(new DOMException('', 'AbortError')); });
      reader.scan({signal: signal}).catch(reject);
    });
  }

  // What is wrong with the tag, or '' if it carries exactly the address of this crate.
  function problemWith(event) {
    var records = event.message.records;
    if (records.length !== 1) return 'Der Tag enthält ' + records.length + ' Einträge statt genau einem.';
    if (records[0].recordType !== 'url') return 'Der Eintrag auf dem Tag ist keine Adresse.';
    var found = new TextDecoder().decode(records[0].data);
    if (found !== url) return 'Auf dem Tag steht „' + found + '“ statt der Adresse dieser Crate.';
    return '';
  }

  function isOtherTag(event) {
    return Boolean(checked && checked.serial && event.serialNumber && event.serialNumber !== checked.serial);
  }

  async function write() {
    checked = null;
    lockButton.hidden = true;
    var signal = begin();
    try {
      say('Tag ans Telefon halten …');
      limit(TAP_SECONDS);
      await new NDEFReader().write({records: [{recordType: 'url', data: url}]}, {signal: signal});

      say('Geschrieben. Jetzt wird geprüft – Tag am Telefon lassen. Passiert nichts, kurz wegnehmen und wieder hinhalten …');
      limit(TAP_SECONDS);
      var event = await readTag(new NDEFReader(), signal);
      var problem = problemWith(event);
      if (problem) {
        say('Prüfung fehlgeschlagen: ' + problem + ' Bitte neu beschreiben.', 'error');
        return;
      }
      checked = {serial: event.serialNumber || ''};
      var which = checked.serial ? ' (Tag ' + checked.serial + ')' : '';
      if (lockable) {
        lockButton.hidden = false;
        say('Geprüft' + which + ': Auf dem Tag steht die Adresse dieser Crate. Er lässt sich noch überschreiben, bis er gesperrt wird.', 'ok');
      } else {
        say('Geprüft' + which + ': Auf dem Tag steht die Adresse dieser Crate. Sperren geht erst, wenn PUBLIC_BASE_URL gesetzt ist.', 'ok');
      }
    } catch (error) {
      say(explain(error), 'error');
    } finally {
      end();
    }
  }

  async function lock() {
    if (!checked) return;
    if (!confirm('Tag endgültig sperren?\n\nDanach lässt er sich nie wieder beschreiben. Die Adresse:\n' + url)) return;
    var signal = begin(), step = running, wrongTag = false;
    try {
      say('Tag ans Telefon halten und liegen lassen – er wird erst noch einmal geprüft …');
      limit(TAP_SECONDS);
      var reader = new NDEFReader();
      var event = await readTag(reader, signal, function (other) {
        // another tag turns up while the lock is waiting: stop, as far as that is still possible
        if (isOtherTag(other) || problemWith(other)) { wrongTag = true; step.abort(); }
      });
      var problem = isOtherTag(event)
        ? 'Das ist ein anderer Tag als der eben geprüfte (' + event.serialNumber + ' statt ' + checked.serial + ').'
        : problemWith(event);
      if (problem) {
        checked = null;
        lockButton.hidden = true;
        say('Nicht gesperrt. ' + problem + ' Bitte neu beschreiben.', 'error');
        return;
      }
      say('Geprüft. Sperre – Tag liegen lassen …');
      limit(LOCK_SECONDS);
      await reader.makeReadOnly({signal: signal});
      checked = null;
      lockButton.hidden = true;
      say('Gesperrt. Der Tag zeigt dauerhaft auf diese Crate.', 'ok');
    } catch (error) {
      if (wrongTag) {
        say('Abgebrochen: Es wurde ein anderer Tag ans Telefon gehalten. Bitte prüfen, ob er gesperrt wurde.', 'error');
      } else if (error && error.name === 'AbortError') {
        say('Nicht gesperrt: Der Tag war nicht mehr am Telefon. Bitte noch einmal versuchen und ihn liegen lassen.', 'error');
      } else {
        say('Nicht gesperrt. ' + explain(error), 'error');
      }
    } finally {
      end();
    }
  }

  writeButton.addEventListener('click', write);
  lockButton.addEventListener('click', lock);
  cancelButton.addEventListener('click', function () { if (running) running.abort(); });
})();
