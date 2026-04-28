from __future__ import annotations

from tkinter import Label, Toplevel

from app_core import BORDER, CARD_ALT, TEXT


class HoverTooltip:
    def __init__(self, root, text_getter, *, targets, wraplength: int = 220, wait_ms: int = 350) -> None:
        self.root = root
        self.text_getter = text_getter
        self.targets = [widget for widget in targets if widget is not None]
        self.wraplength = wraplength
        self.wait_ms = wait_ms
        self.tooltip_window = None
        self.label = None
        self.after_id = None
        self.last_pointer_x = 0
        self.last_pointer_y = 0

        for widget in self.targets:
            widget.bind("<Enter>", self._on_enter, add="+")
            widget.bind("<Leave>", self._on_leave, add="+")
            widget.bind("<Motion>", self._on_motion, add="+")
            widget.bind("<ButtonPress-1>", self._on_leave, add="+")
            widget.bind("<Destroy>", self._on_destroy, add="+")

    def _on_enter(self, event) -> None:  # type: ignore[no-untyped-def]
        self.last_pointer_x = event.x_root
        self.last_pointer_y = event.y_root
        self._schedule_show()

    def _on_motion(self, event) -> None:  # type: ignore[no-untyped-def]
        self.last_pointer_x = event.x_root
        self.last_pointer_y = event.y_root
        if self.tooltip_window is not None:
            self._position_tooltip()

    def _on_leave(self, _event=None) -> None:
        self._cancel_scheduled_show()
        self._hide()

    def _on_destroy(self, _event=None) -> None:
        self._cancel_scheduled_show()
        self._hide()

    def _schedule_show(self) -> None:
        self._cancel_scheduled_show()
        self.after_id = self.root.after(self.wait_ms, self._show)

    def _cancel_scheduled_show(self) -> None:
        if self.after_id is not None:
            try:
                self.root.after_cancel(self.after_id)
            except Exception:
                pass
            self.after_id = None

    def _show(self) -> None:
        self.after_id = None
        tooltip_text = self._get_text()
        if not tooltip_text:
            return

        if self.tooltip_window is None or not self.tooltip_window.winfo_exists():
            self.tooltip_window = Toplevel(self.root)
            self.tooltip_window.withdraw()
            self.tooltip_window.overrideredirect(True)
            self.tooltip_window.transient(self.root)
            self.tooltip_window.configure(bg=BORDER)

            self.label = Label(
                self.tooltip_window,
                text=tooltip_text,
                justify="left",
                anchor="w",
                bg=CARD_ALT,
                fg=TEXT,
                bd=0,
                padx=8,
                pady=6,
                wraplength=self.wraplength,
            )
            self.label.pack()
        else:
            self.label.configure(text=tooltip_text)

        self._position_tooltip()
        self.tooltip_window.deiconify()
        self.tooltip_window.lift()

    def _position_tooltip(self) -> None:
        if self.tooltip_window is None or not self.tooltip_window.winfo_exists():
            return
        x = self.last_pointer_x + 12
        y = self.last_pointer_y + 18
        self.tooltip_window.geometry(f"+{x}+{y}")

    def _hide(self) -> None:
        if self.tooltip_window is not None and self.tooltip_window.winfo_exists():
            try:
                self.tooltip_window.destroy()
            except Exception:
                pass
        self.tooltip_window = None
        self.label = None

    def _get_text(self) -> str:
        try:
            value = self.text_getter()
        except Exception:
            return ""
        return str(value or "").strip()
