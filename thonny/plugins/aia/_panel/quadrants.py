# Copyright (c) 2026 Jakub Šenkýř
# SPDX-License-Identifier: MIT
"""The default layout of Thonny AIA: four quadrants (Jakub 2026-10-15, cortex-zamestnani#78).

    editor | AIA's answers
    -------+--------------
    Shell  | AIA's input

The left and the right half are 1:1, the top row (editor, answers) takes 75 % of the height and
the bottom row (Shell, AIA's input) 25 %, at least the height of AIA's input with its buttons.
The border between AIA's answers and its input runs at the height of the border above the Shell.

Only for a fresh configuration ("Rozložení panelů bych nikomu nenutil."): a configuration that has
the width of the east column stored (every earlier beta stores it when Thonny closes) keeps its
layout. The option ``layout.aia_quadrants`` holds the mode and is stored, so it lasts:

- ``proportional``: the 1:1 and 75:25 proportions hold also when the window changes size
  (maximizing), and AIA's border follows the Shell's;
- ``aligned``: after the user moves the border between the editor and AIA or above the Shell,
  Thonny keeps the sizes as usual, AIA's border still follows the Shell's;
- ``off``: AIA's input keeps its own height (stored in ``aia.input_height`` when the user moves
  AIA's border; the smallest height that fits the input and its buttons otherwise).
"""

import logging

logger = logging.getLogger(__name__)

OPTION = "layout.aia_quadrants"
PROPORTIONAL, ALIGNED, OFF = "proportional", "aligned", "off"
BOTTOM_SHARE = 0.25
INPUT_HEIGHT_OPTION = "aia.input_height"  # 0 = the smallest height that fits


def init_option(wb) -> None:
    """Decide the mode once for a configuration: quadrants only for a fresh one."""
    ini = wb._configuration_manager._ini
    if ini.has_option("layout", "aia_quadrants"):
        wb.set_default(OPTION, OFF)
    else:
        fresh = not ini.has_option("layout", "east_pw_width")
        wb.set_default(OPTION, OFF)
        wb.set_option(OPTION, PROPORTIONAL if fresh else OFF)
    wb.set_default(INPUT_HEIGHT_OPTION, 0)


def bottom_height(main_height: int, minimum: int) -> int:
    """Height of the bottom row: a quarter of the height, never less than the minimum."""
    return max(round(main_height * BOTTOM_SHARE), minimum)


def east_width(main_width: int, sash: int) -> int:
    """Preferred size of the east column for halves of the same size. AutomaticPanedWindow gives
    the last pane its preferred size minus the sash before it, so this is half plus the sash."""
    return max((main_width + sash) // 2, 1)


def input_height_aligned(split_bottom: int, shell_top: int) -> int:
    """Height of AIA's input pane whose top is at the top of the Shell's notebook."""
    return split_bottom - shell_top


class Quadrants:
    """Keeps the quadrants of one workbench and one AIA view."""

    def __init__(self, wb, view):
        self._wb = wb
        self._view = view
        self._pending = False
        for pw in (wb._main_pw, wb._center_pw):
            pw.bind("<ButtonRelease-1>", self._on_workbench_sash_released, True)
        wb._main_pw.bind("<Configure>", self._schedule, True)
        self._shell_nb().bind("<Configure>", self._schedule, True)
        view.split.bind("<Configure>", self._schedule, True)
        view.split.bind("<ButtonRelease-1>", self._on_aia_sash_released, True)
        self._schedule()

    def mode(self) -> str:
        return self._wb.get_option(OPTION)

    def _shell_nb(self):
        return self._wb._view_notebooks["s"]

    def _on_workbench_sash_released(self, event):
        if event.widget in (self._wb._main_pw, self._wb._center_pw) and self.mode() == PROPORTIONAL:
            self._wb.set_option(OPTION, ALIGNED)

    def _on_aia_sash_released(self, event):
        if event.widget is self._view.split:
            self._wb.set_option(OPTION, OFF)
            self._wb.set_option(INPUT_HEIGHT_OPTION, self._view.input_pane.winfo_height())

    def _schedule(self, event=None):
        if not self._pending:
            self._pending = True
            self._wb.after_idle(self._apply)

    def _arranged(self) -> bool:
        """The panes are where the quadrants expect them: nothing on the west, the Shell below the
        editor, AIA alone in the north-east."""
        wb = self._wb
        try:
            east = wb._east_pw
            ne = wb._view_notebooks["ne"]
            return (
                not wb._west_pw.is_visible()
                and east.is_visible()
                and east.pane_widgets() == [ne]
                and self._view.home_widget.master is ne
                and self._shell_nb().is_visible()
                and wb.get_view("ShellView").home_widget.master is self._shell_nb()
            )
        except Exception:
            logger.debug("Could not check the layout", exc_info=True)
            return False

    def _apply(self):
        self._pending = False
        try:
            if getattr(self._wb, "initializing", False):
                self._wb.after(100, self._schedule)
                return
            mode = self.mode()
            arranged = self._arranged()
            if mode == PROPORTIONAL and arranged:
                self._proportions()
            if mode in (PROPORTIONAL, ALIGNED) and arranged:
                self._align()
            else:
                self._own_height()
        except Exception:
            logger.debug("Could not apply the quadrants", exc_info=True)

    def _proportions(self):
        wb = self._wb
        main = wb._main_pw
        if main.winfo_width() < 20 or wb._center_pw.winfo_height() < 20:
            return
        sash = int(str(main.cget("sashwidth")))
        width = east_width(main.winfo_width(), sash)
        center_sash = int(str(wb._center_pw.cget("sashwidth")))
        # the last pane gets its preferred size minus the sash before it
        height = bottom_height(wb._center_pw.winfo_height(), self._bottom_minimum()) + center_sash
        changed = False
        if wb._east_pw.preferred_size_in_pw != width:
            wb._east_pw.preferred_size_in_pw = width
            changed = True
        if self._shell_nb().preferred_size_in_pw != height:
            self._shell_nb().preferred_size_in_pw = height
            changed = True
        if changed:
            main._check_restore_preferred_sizes()
            wb._center_pw._check_restore_preferred_sizes()

    def _bottom_minimum(self) -> int:
        """AIA's input pane starts at the top of the Shell's notebook, so the Shell's notebook needs
        the height of AIA's input, plus what AIA's panel ends above the Shell's notebook."""
        s_nb, split = self._shell_nb(), self._view.split
        lower = (s_nb.winfo_rooty() + s_nb.winfo_height()) - (split.winfo_rooty() + split.winfo_height())
        return self._view.input_minimum() + max(lower, 0)

    def _align(self):
        split = self._view.split
        if split.winfo_height() < 20:
            return
        height = input_height_aligned(
            split.winfo_rooty() + split.winfo_height(), self._shell_nb().winfo_rooty()
        )
        self._view.set_input_height(max(height, self._view.input_minimum()))

    def _own_height(self):
        stored = self._wb.get_option(INPUT_HEIGHT_OPTION) or 0
        self._view.set_input_height(max(stored, self._view.input_minimum()))
