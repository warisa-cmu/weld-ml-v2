"""Jupyter widget for the lab demo: weld and measure a mock weld one button at a time.

    from _mock.lab_widget import LabDemo
    LabDemo(experiment_file, lab).show()

The widget reads the planned settings from the experiments spreadsheet but
never writes to it: the experimenter types each value into Excel, as in the
real lab. The panel on the right lists exactly which cell gets which value.
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any, Callable

import ipywidgets as w
import pandas as pd

from common import settings, sheet

from .lab import LabError, MockLab, ProtocolError

_COLOURS = {"ok": "#1b7f3b", "protocol": "#b35c00", "error": "#b00020", "info": "#333"}


class LabDemo:
    def __init__(self, experiment_file: str | Path, lab: MockLab):
        self.experiment_file = Path(experiment_file)
        self.lab = lab
        self.plan = pd.DataFrame()

        self.weld_dd = w.Dropdown(description="Weld", layout=w.Layout(width="420px"))
        self.refresh_btn = w.Button(description="Reload sheet", icon="refresh")
        self.planned = w.HTML()
        self.R = w.IntText(description="R")
        self.W = w.IntText(description="W")
        self.D = w.IntText(description="D")
        self.P = w.BoundedFloatText(description="P", step=0.005, min=0.0, max=1.0)
        self.O = w.Dropdown(description="O", options=list(settings.ORIENTATIONS))
        for box in (self.R, self.W, self.D, self.P, self.O):
            box.layout = w.Layout(width="170px")

        self.weld_btn = w.Button(description="1. Weld", button_style="primary", icon="fire")
        self.inspect_btn = w.Button(description="2. Visual inspection", icon="eye")
        self.stress_btns = [w.Button(description=f"3. Read stress P{p}") for p in range(1, settings.N_POSITIONS + 1)]
        self.cut_btn = w.Button(description="4. Cut specimens", icon="cut")
        self.specimen_btns = [
            w.Button(description=f"5. Tensile specimen {k}") for k in range(1, settings.N_TENSILE_SPECIMENS + 1)
        ]
        self.discard_btn = w.Button(description="Discard weld", button_style="danger", icon="trash")
        self.force = w.Checkbox(description="Override protocol warnings", indent=False)

        self.message = w.HTML()
        self.card = w.HTML()
        self._discard_armed = False
        self._suppress = False

        self.refresh_btn.on_click(lambda _: self.reload())
        self.weld_dd.observe(lambda _: self._select(), names="value")
        self.weld_btn.on_click(lambda _: self._run(self._weld))
        self.inspect_btn.on_click(lambda _: self._run(self._inspect))
        for p, b in enumerate(self.stress_btns, start=1):
            b.on_click(lambda _, p=p: self._run(lambda: self._stress(p)))
        self.cut_btn.on_click(lambda _: self._run(self._cut))
        for k, b in enumerate(self.specimen_btns, start=1):
            b.on_click(lambda _, k=k: self._run(lambda: self._specimen(k)))
        self.discard_btn.on_click(lambda _: self._discard())

        left = w.VBox(
            [
                w.HBox([self.weld_dd, self.refresh_btn]),
                self.planned,
                w.HBox([self.R, self.W, self.D]),
                w.HBox([self.P, self.O]),
                self.weld_btn,
                self.inspect_btn,
                w.HBox(self.stress_btns),
                self.cut_btn,
                w.HBox(self.specimen_btns),
                w.HBox([self.force, self.discard_btn]),
                self.message,
            ],
            layout=w.Layout(width="560px"),
        )
        self.widget = w.HBox([left, self.card])
        self.reload()

    # ------------------------------------------------------------------ public
    def show(self):
        return self.widget

    def reload(self) -> None:
        current = self.weld_dd.value
        self.plan = pd.read_excel(self.experiment_file, sheet_name=sheet.SHEET, dtype=object)
        self.plan = self.plan.dropna(subset=["weld_id"]).sort_values(["batch", "order_in_batch"])
        options = []
        for _, r in self.plan.iterrows():
            mark = " ✓" if self.lab.exists(r["weld_id"]) else ""
            options.append((f"{r['weld_id']} · batch {r['batch']} · #{r['order_in_batch']} · {r['type']}{mark}", r["weld_id"]))
        self._suppress = True
        try:
            self.weld_dd.options = options
            ids = [v for _, v in options]
            self.weld_dd.value = current if current in ids else (ids[0] if ids else None)
        finally:
            self._suppress = False
        self._select()

    # ----------------------------------------------------------------- actions
    @property
    def weld_id(self) -> str | None:
        return self.weld_dd.value

    def _row(self) -> pd.Series:
        return self.plan[self.plan["weld_id"] == self.weld_id].iloc[0]

    def _select(self) -> None:
        if self._suppress:
            return
        self._discard_armed = False
        self.discard_btn.description = "Discard weld"
        if self.weld_id is None:
            self._refresh()
            return
        r = self._row()
        self.R.value, self.W.value, self.D.value = (int(round(float(r[c]))) for c in "RWD")
        self.P.value = float(r["P"])
        self.O.value = r["O"]
        self.planned.value = (
            f"<b>Planned:</b> R {int(float(r['R']))}, W {int(float(r['W']))}, D {int(float(r['D']))}, "
            f"P {float(r['P']):.3f}, O {r['O']}. Edit the boxes to weld at different settings."
        )
        self._say("info", f"Selected {self.weld_id}.")
        self._refresh()

    def _run(self, action: Callable[[], str]) -> None:
        self._discard_armed = False
        self.discard_btn.description = "Discard weld"
        try:
            self._say("ok", action())
        except ProtocolError as exc:
            self._say("protocol", f"Protocol: {exc} Tick 'Override protocol warnings' to do it anyway.")
        except (LabError, ValueError) as exc:
            self._say("error", str(exc))
        self._refresh()

    def _weld(self) -> str:
        s = {"R": self.R.value, "W": self.W.value, "D": self.D.value, "P": round(self.P.value, 4), "O": self.O.value}
        self.lab.weld(self.weld_id, **s)
        r = self._row()
        changed = [k for k in s if (s[k] != r[k] if k == "O" else abs(float(s[k]) - float(r[k])) > 1e-9)]
        note = f" Settings differ from the plan ({', '.join(changed)}): overwrite them in the sheet and add a note." if changed else ""
        self._mark_welded()
        return f"{self.weld_id} welded.{note}"

    def _inspect(self) -> str:
        q = self.lab.inspect(self.weld_id)
        extra = " Code D1: stop here, measure nothing else." if q == 0 else ""
        return f"Visual quality: {q}.{extra}"

    def _stress(self, p: int) -> str:
        v = self.lab.read_stress(self.weld_id, p, force=self.force.value)
        return f"Stress reading at P{p}: {v:.1f} MPa."

    def _cut(self) -> str:
        self.lab.cut_specimens(self.weld_id, force=self.force.value)
        return "Tensile specimens cut. The weld can no longer be read for stress."

    def _specimen(self, k: int) -> str:
        uts, fracture = self.lab.test_specimen(self.weld_id, k)
        return f"Specimen {k}: UTS {uts:.1f} MPa, fracture in {fracture}."

    def _discard(self) -> None:
        if not self.lab.exists(self.weld_id):
            self._say("info", f"{self.weld_id} has not been welded; nothing to discard.")
            return
        if not self._discard_armed:
            self._discard_armed = True
            self.discard_btn.description = "Click again to confirm"
            self._say("protocol", f"Discard {self.weld_id}? All its measurements are lost.")
            return
        self.lab.discard(self.weld_id)
        self._discard_armed = False
        self.discard_btn.description = "Discard weld"
        self._mark_welded()
        self._say("info", f"{self.weld_id} discarded. It can be welded again.")
        self._refresh()

    def _mark_welded(self) -> None:
        """Update the ✓ marks in the dropdown without re-selecting the weld."""
        current = self.weld_dd.value
        self._suppress = True
        try:
            self.weld_dd.options = [
                (label.replace(" ✓", "") + (" ✓" if self.lab.exists(v) else ""), v)
                for label, v in self.weld_dd.options
            ]
            self.weld_dd.value = current
        finally:
            self._suppress = False

    # ----------------------------------------------------------------- display
    def _say(self, kind: str, text: str) -> None:
        self.message.value = f"<div style='color:{_COLOURS[kind]};margin-top:6px'>{html.escape(text)}</div>"

    def _refresh(self) -> None:
        state = self.lab.state(self.weld_id) if self.weld_id and self.lab.exists(self.weld_id) else None
        welded = state is not None
        cut = bool(state and state["specimens_cut"])
        self.weld_btn.disabled = welded or self.weld_id is None
        for box in (self.R, self.W, self.D, self.P, self.O):
            box.disabled = welded
        self.inspect_btn.disabled = not welded
        for b in self.stress_btns:
            b.disabled = not welded or cut
        self.cut_btn.disabled = not welded or cut
        for k, b in enumerate(self.specimen_btns, start=1):
            b.disabled = not cut or state["specimens"][str(k)] is not None
        self.discard_btn.disabled = not welded
        self.card.value = self._card(state)

    def _card(self, state: dict[str, Any] | None) -> str:
        head = f"<h4 style='margin:0 0 6px'>Weld {html.escape(str(self.weld_id))}</h4>"
        if state is None:
            return _box(head + "<i>Not welded yet.</i>")
        rows: list[tuple[str, str]] = []
        s = state["settings"]
        rows.append(("settings used", f"R {s['R']}, W {s['W']}, D {s['D']}, P {s['P']:.3f}, O {s['O']}"))
        q = state["visual_quality"]
        rows.append(("visual_quality", "—" if q is None else str(q)))
        notes = []
        for p in range(1, settings.N_POSITIONS + 1):
            readings = state["stress"][str(p)]
            for k, v in enumerate(readings, start=1):
                col = f"stress_p{p}_r{k}" if k <= settings.MAX_REPEATS else f"(extra, in notes) P{p} #{k}"
                rows.append((col, f"{v:.1f}"))
            if len(readings) > settings.MAX_REPEATS:
                notes.append(f"P{p} has {len(readings)} readings; the sheet holds {settings.MAX_REPEATS}.")
        for k in range(1, settings.N_TENSILE_SPECIMENS + 1):
            specimen = state["specimens"][str(k)]
            if specimen:
                rows.append((f"uts_{k}", f"{specimen['uts']:.1f}"))
                rows.append((f"fracture_{k}", specimen["fracture"]))
            elif state["specimens_cut"]:
                rows.append((f"uts_{k}", "<i>specimen not tested</i>"))
        table = "".join(
            f"<tr><td style='padding:2px 10px 2px 0;font-family:monospace'>{html.escape(k)}</td>"
            f"<td style='padding:2px 0'><b>{v}</b></td></tr>"
            for k, v in rows
        )
        foot = "".join(f"<div style='color:#b35c00'>{html.escape(n)}</div>" for n in notes)
        return _box(
            head
            + "<div style='color:#555;margin-bottom:4px'>Type these into the spreadsheet row:</div>"
            + f"<table>{table}</table>{foot}"
        )


def _box(inner: str) -> str:
    return (
        "<div style='border:1px solid #ccc;border-radius:6px;padding:10px 14px;"
        f"min-width:300px;margin-left:16px'>{inner}</div>"
    )
