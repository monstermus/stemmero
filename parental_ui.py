"""PIN-dialoger til forældre. Root-vinduet håndhæver adgang til indstillinger."""
from contextlib import contextmanager
import time
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from parental_pin import PinStoreError

SESSION_SECONDS = 120


class ParentControls:
    def __init__(self, parent, store, on_unlock, on_lock, recovery_default=True, *, clock=time.monotonic):
        self.parent = parent
        self.store = store
        self.on_unlock = on_unlock
        self.on_lock = on_lock
        self.recovery_default = recovery_default
        self.clock = clock
        self.busy = False
        self._unlocked = False
        self.unlocked_until = 0.0
        self.frame = ttk.LabelFrame(parent, text='Forældreindstillinger', padding=8)
        self.status = tk.StringVar(parent)
        ttk.Label(self.frame, textvariable=self.status, wraplength=640).grid(
            row=0, column=0, columnspan=5, sticky='w', pady=(0, 8))
        self.setup_button = ttk.Button(self.frame, text='Opret PIN', command=self.setup)
        self.unlock_button = ttk.Button(self.frame, text='Lås op', command=self.unlock)
        self.lock_button = ttk.Button(self.frame, text='Lås indstillinger', command=self.lock)
        self.change_button = ttk.Button(self.frame, text='Skift PIN', command=self.change_pin)
        self.recovery_button = ttk.Button(self.frame, text='Glemt PIN', command=self.recover)
        for column, button in enumerate(self._buttons):
            button.grid(row=1, column=column, padx=(0, 8) if column < 4 else 0, sticky='w')
        self.refresh()

    @property
    def _buttons(self):
        return (self.setup_button, self.unlock_button, self.lock_button,
                self.change_button, self.recovery_button)

    @property
    def unlocked(self):
        return self._unlocked

    def lock(self):
        self._unlocked = False
        self.unlocked_until = 0.0
        self.on_lock()
        self.refresh()

    def _unlock_session(self):
        self._unlocked = True
        self.unlocked_until = self.clock() + SESSION_SECONDS
        self.on_unlock()
        self.refresh()

    def refresh(self):
        configured = self.store.configured
        damaged = self.store.damaged
        if damaged:
            if self._unlocked:
                self._unlocked = False
                self.unlocked_until = 0.0
                self.on_lock()
            self.status.set('PIN-data kan ikke læses. Indstillingerne forbliver låst. En voksen skal reparere opsætningen.')
        elif not configured:
            self.status.set('En voksen skal oprette en PIN, før indstillingerne kan ændres.')
        elif self._unlocked:
            self.status.set('Indstillingerne låser efter 2 minutters inaktivitet. Lås dem, før barnet overtager.')
        else:
            self.status.set('Indstillingerne er låst. En voksen kan låse op med PIN.')
        states = (not configured and not damaged, configured and not damaged and not self._unlocked,
                  self._unlocked and not damaged, configured and not damaged, False)
        if configured and not damaged:
            try:
                states = (*states[:4], self.store.recovery_enabled)
            except PinStoreError:
                states = (False,) * 5
                if self._unlocked:
                    self._unlocked = False
                    self.unlocked_until = 0.0
                    self.on_lock()
                self.status.set('PIN-data kan ikke læses. Indstillingerne forbliver låst.')
        for button, enabled in zip(self._buttons, states):
            button.configure(state='normal' if enabled and not self.busy else 'disabled')

    @contextmanager
    def _modal(self):
        self.busy = True
        self.refresh()
        try:
            yield
        except (PinStoreError, PermissionError, ValueError) as error:
            self.lock()
            messagebox.showerror('PIN', str(error), parent=self.parent)
        finally:
            self.busy = False
            self.refresh()

    def _ask_pin(self, title, prompt):
        return simpledialog.askstring(title, prompt, show='*', parent=self.parent)

    def _new_pin(self, title):
        pin = self._ask_pin(title, 'Vælg en PIN på 4 til 12 cifre.')
        if pin is None:
            return None
        confirmation = self._ask_pin(title, 'Gentag den nye PIN.')
        if confirmation is None:
            return None
        if pin != confirmation:
            raise ValueError('De to PIN-koder er ikke ens. PIN er ikke ændret.')
        return pin

    def _auth_failed(self):
        self.lock()
        remaining = self.store.remaining_lock_seconds
        text = f'For mange forsøg. Prøv igen om {remaining} sekunder.' if remaining else 'Forkert PIN.'
        messagebox.showerror('Indstillingerne er låst', text, parent=self.parent)

    def setup(self):
        if self.busy:
            return
        with self._modal():
            pin = self._new_pin('Opret PIN')
            if pin is None:
                return
            code = self.store.setup(pin, enable_recovery=self.recovery_default)
            if code:
                self._show_recovery_code(code)
            self._unlock_session()

    def unlock(self):
        if self.busy:
            return
        with self._modal():
            pin = self._ask_pin('Lås indstillinger op', 'Indtast din PIN.')
            if pin is None:
                return
            if self.store.verify(pin):
                self._unlock_session()
            else:
                self._auth_failed()

    def fresh_auth(self):
        """Kræv en ny PIN-kontrol, også mens indstillingerne er låst op."""
        if self.busy:
            return False
        result = False
        with self._modal():
            if not self.store.configured:
                messagebox.showerror('PIN mangler', 'En voksen skal først oprette en PIN.', parent=self.parent)
                return False
            pin = self._ask_pin('Bekræft med PIN', 'Indtast din PIN for at godkende handlingen.')
            if pin is None:
                return False
            result = self.store.verify(pin)
            if not result:
                self._auth_failed()
        return result

    def change_pin(self):
        if self.busy:
            return
        with self._modal():
            previous = self._ask_pin('Skift PIN', 'Indtast din nuværende PIN.')
            if previous is None:
                return
            new = self._new_pin('Skift PIN')
            if new is None:
                return
            self.store.change_pin(previous, new)
            self._unlock_session()

    def recover(self):
        if self.busy:
            return
        with self._modal():
            code = self._ask_pin('Glemt PIN', 'Indtast din gendannelseskode.')
            if code is None:
                return
            new = self._new_pin('Vælg ny PIN')
            if new is None:
                return
            replacement = self.store.recover(code, new)
            self._show_recovery_code(replacement)
            self._unlock_session()

    def _show_recovery_code(self, code):
        dialog = tk.Toplevel(self.parent)
        dialog.title('Gem din gendannelseskode')
        dialog.transient(self.parent)
        dialog.resizable(False, False)
        content = ttk.Frame(dialog, padding=16)
        content.pack(fill='both', expand=True)
        ttk.Label(content, text='Gem koden et privat sted. Den kan nulstille din PIN og vises kun nu.',
                  wraplength=430).pack(anchor='w', pady=(0, 12))
        value = tk.StringVar(dialog, value=code)
        field = ttk.Entry(content, textvariable=value, state='readonly', width=43)
        field.pack(fill='x')

        def copy_code():
            dialog.clipboard_clear()
            dialog.clipboard_append(code)

        actions = ttk.Frame(content)
        actions.pack(fill='x', pady=(12, 0))
        ttk.Button(actions, text='Kopiér kode', command=copy_code).pack(side='left')
        ttk.Button(actions, text='Jeg har gemt koden', command=dialog.destroy).pack(side='right')
        dialog.bind('<Escape>', lambda _event: dialog.destroy())
        dialog.bind('<Return>', lambda _event: dialog.destroy())
        dialog.grab_set()
        field.focus_set()
        field.selection_range(0, 'end')
        self.parent.wait_window(dialog)
