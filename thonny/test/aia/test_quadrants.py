# Copyright (c) 2026 Jakub Šenkýř
# SPDX-License-Identifier: MIT
"""The default layout in quadrants (cortex-zamestnani#78): sizes, and only for a fresh
configuration."""
from configparser import ConfigParser
from types import SimpleNamespace

from thonny.plugins.aia._panel import quadrants
from thonny.plugins.aia._panel.quadrants import (
    ALIGNED,
    OFF,
    OPTION,
    PROPORTIONAL,
    Quadrants,
    bottom_height,
    east_width,
    init_option,
    input_height_aligned,
)


class FakeWorkbench:
    def __init__(self, ini_text=""):
        ini = ConfigParser(interpolation=None)
        ini.read_string(ini_text)
        self._configuration_manager = SimpleNamespace(_ini=ini)
        self.options = {}
        self.defaults = {}

    def set_default(self, name, value):
        self.defaults[name] = value

    def set_option(self, name, value):
        self.options[name] = value

    def get_option(self, name):
        return self.options.get(name, self.defaults.get(name))


def test_fresh_configuration_gets_quadrants():
    wb = FakeWorkbench()
    init_option(wb)
    assert wb.get_option(OPTION) == PROPORTIONAL


def test_stored_layout_of_an_earlier_beta_stays():
    wb = FakeWorkbench("[layout]\neast_pw_width = 200\n")
    init_option(wb)
    assert wb.get_option(OPTION) == OFF


def test_stored_mode_is_not_decided_again():
    # the mode is stored at the first start; the next start reads it from the configuration
    wb = FakeWorkbench("[layout]\naia_quadrants = proportional\neast_pw_width = 391\n")
    init_option(wb)
    assert OPTION not in wb.options
    assert wb.defaults[OPTION] == OFF


def test_bottom_row_is_a_quarter_but_never_below_the_minimum():
    assert bottom_height(592, 85) == 148
    assert bottom_height(375, 130) == 130


def test_east_column_preference_gives_equal_halves():
    # AutomaticPanedWindow: center = main - preferred, east = preferred - sash
    main, sash = 788, 6
    preferred = east_width(main, sash)
    assert main - preferred == preferred - sash


def test_aia_input_starts_at_the_top_of_the_shell():
    assert input_height_aligned(split_bottom=728, shell_top=580) == 148


def _quadrants(wb):
    q = Quadrants.__new__(Quadrants)
    q._wb = wb
    q._view = SimpleNamespace(
        split="split", input_pane=SimpleNamespace(winfo_height=lambda: 120)
    )
    return q


def test_moving_a_workbench_border_ends_the_proportions_only():
    wb = FakeWorkbench()
    wb._main_pw, wb._center_pw = "main", "center"
    wb.set_option(OPTION, PROPORTIONAL)
    q = _quadrants(wb)
    q._on_workbench_sash_released(SimpleNamespace(widget="text"))  # a click inside a pane
    assert wb.get_option(OPTION) == PROPORTIONAL
    q._on_workbench_sash_released(SimpleNamespace(widget="center"))
    assert wb.get_option(OPTION) == ALIGNED


def test_moving_aias_border_keeps_its_height():
    wb = FakeWorkbench()
    wb.set_option(OPTION, ALIGNED)
    q = _quadrants(wb)
    q._on_aia_sash_released(SimpleNamespace(widget="split"))
    assert wb.get_option(OPTION) == OFF
    assert wb.get_option(quadrants.INPUT_HEIGHT_OPTION) == 120
