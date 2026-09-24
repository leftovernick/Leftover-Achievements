// Run with: node tests/confirm_frontend.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const script = fs.readFileSync(path.join(__dirname, '..', 'static/js/confirm.js'), 'utf8');
const trigger = { addEventListener(_name, callback) { this.click = callback; } };
const form = {
  dataset: { confirmTitle: 'Remove player?', confirmMessage: 'Confirm removal.', confirmLabel: 'Remove' },
  querySelector() { return trigger; },
};
const dialogs = [];
const document = {
  querySelectorAll() { return [form]; },
  createElement() {
    const fields = {
      h2: {}, p: {}, '[value="confirm"]': {}, '[value="cancel"]': { focus() {} },
    };
    const dialog = {
      returnValue: '',
      querySelector(selector) { return fields[selector]; },
      addEventListener(_name, callback) { this.close = callback; },
      showModal() { this.open = true; },
      remove() { this.removed = true; },
      fields,
    };
    dialogs.push(dialog);
    return dialog;
  },
  body: { append() {} },
};
function HTMLFormElement() {}
HTMLFormElement.prototype.submit = function () { this.submitted = true; };
function HTMLDialogElement() {}
HTMLDialogElement.prototype.showModal = function () {};
const window = {};
vm.runInNewContext(script, { window, document, HTMLFormElement, HTMLDialogElement });

(async () => {
  const cancelled = trigger.click();
  assert.equal(form.submitted, undefined);
  dialogs[0].returnValue = 'cancel';
  dialogs[0].close();
  await cancelled;
  assert.equal(form.submitted, undefined);
  assert.equal(dialogs[0].removed, true);

  const confirmed = trigger.click();
  assert.equal(dialogs[1].fields.h2.textContent, 'Remove player?');
  assert.equal(dialogs[1].fields.p.textContent, 'Confirm removal.');
  assert.equal(dialogs[1].fields['[value="confirm"]'].textContent, 'Remove');
  dialogs[1].returnValue = 'confirm';
  dialogs[1].close();
  await confirmed;
  assert.equal(form.submitted, true);
  process.stdout.write('In-app confirmation tests passed.\n');
})().catch((error) => { console.error(error); process.exitCode = 1; });
