"""Colour themes for the dashboard.

Every project stores the name of the theme it uses, so switching projects can
change the whole look of the app. Each theme defines:

    label   what the picker shows
    accent  borders, headings, the progress bar fill
    soft    the dim companion used for supporting text
    bright  a stronger shade for values that should stand out

Colours are Rich colour *names*, never hex values. A hex would force truecolor
escape codes that render as garbage on 8- and 256-colour terminals; named
colours are quantised by Rich so the dashboard stays readable everywhere.
"""

# Twenty-one colours, all vivid: no greys, no muddy browns, and no two that
# read as the same in the picker. Every pair is separated by hue, or by a
# full step in lightness where the hue repeats (jade/forest, red/garnet).
# The distances were checked in Lab space with CIEDE2000 - the closest pair
# now sits around 15, where the look-alikes this list replaced sat between
# 4 and 13. A name cut from this list is not lost: heal moves a project
# still holding it onto its nearest survivor, so the project keeps a look
# instead of falling back to the default (see RETIRED_THEMES in store.py).
THEMES = {
    "jade":       {"label": "Jade",       "accent": "green3",            "bright": "bright_green"},
    "teal":       {"label": "Teal",       "accent": "turquoise2",        "bright": "bright_cyan"},
    "mint":       {"label": "Mint",       "accent": "medium_spring_green", "bright": "bright_green"},
    "forest":     {"label": "Forest",     "accent": "green4",            "bright": "bright_green"},
    "pine":       {"label": "Pine",       "accent": "dark_cyan",         "bright": "bright_cyan"},
    "moss":       {"label": "Moss",       "accent": "yellow4",           "bright": "bright_yellow"},
    "cobalt":     {"label": "Cobalt",     "accent": "deep_sky_blue4",    "bright": "bright_blue"},
    "cornflower": {"label": "Cornflower", "accent": "cornflower_blue",   "bright": "bright_cyan"},
    "royal":      {"label": "Royal",      "accent": "blue3",             "bright": "bright_blue"},
    "lavender":   {"label": "Lavender",   "accent": "medium_purple1",    "bright": "bright_blue"},
    "violet":     {"label": "Violet",     "accent": "dark_violet",       "bright": "bright_magenta"},
    "rose":       {"label": "Rose",       "accent": "deep_pink1",        "bright": "bright_magenta"},
    "raspberry":  {"label": "Raspberry",  "accent": "deep_pink4",        "bright": "bright_magenta"},
    "blossom":    {"label": "Blossom",    "accent": "pink1",             "bright": "bright_magenta"},
    "coral":      {"label": "Coral",      "accent": "indian_red1",       "bright": "bright_red"},
    "red":        {"label": "Red",        "accent": "red3",              "bright": "bright_red"},
    "garnet":     {"label": "Garnet",     "accent": "dark_red",          "bright": "bright_red"},
    "tangerine":  {"label": "Tangerine",  "accent": "dark_orange3",      "bright": "bright_yellow"},
    "apricot":    {"label": "Apricot",    "accent": "sandy_brown",       "bright": "bright_yellow"},
    "bronze":     {"label": "Bronze",     "accent": "dark_goldenrod",    "bright": "bright_yellow"},
    "gold":       {"label": "Gold",       "accent": "gold1",             "bright": "bright_yellow"},
}

DEFAULT_THEME = "jade"

# Picker order, which is also the menu number for each theme: greens, then
# teals and blues, then purples, pinks, reds, oranges and yellows.
ORDER = ["jade", "teal", "mint", "forest", "pine", "moss",
         "cobalt", "cornflower", "royal", "lavender", "violet", "rose",
         "raspberry", "blossom", "coral", "red", "garnet",
         "tangerine", "apricot", "bronze", "gold"]

# Every theme shares one dim companion, kept here so there is a single place
# to change it if that ever needs to vary per theme.
DEFAULT_SOFT = "bright_black"


def theme(key):
    """The palette for a theme name, falling back to the default."""
    return THEMES.get(key, THEMES[DEFAULT_THEME])


def label(key):
    return theme(key)["label"]


def accent(key):
    return theme(key)["accent"]


def soft(key=None):
    return theme(key).get("soft", DEFAULT_SOFT)


def bright(key):
    return theme(key)["bright"]


def choices():
    """[(label, key)] for the theme picker, in menu order."""
    return [(label(k), k) for k in ORDER]