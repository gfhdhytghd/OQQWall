"""A compendium of commonly-used regular expressions.

Objects exported by the package may be in either `UPPERCASE`,
`CamelCase`, or `lower_case`:

- `UPPERCASE`: These are compiled regular expressions, of type
  `Pattern`, which is the result of `re.compile()`.

- `CamelCase`: These are classes whose `__new__()` method returns
  a compiled regular expression, but takes a few additional parameters
  that add optionality to the compiled result.  For instance, the
  `Number`class lets you allow or disallow leading zeros and commas.

- `lower_case`: These are traditional functions built around the
  package's regex constants.  They do not share any consistency in their
  call syntax or result type.

Sources
=======
[1]     Goyvaerts, Jan & Steven Levithan.  Regular Expressions Cookbook,
        2nd ed.  Sebastopol: O'Reilly, 2012.
[2]     Friedl, Jeffrey.  Mastering Regular Expressions, 3rd ed.
        Sebastopol: O'Reilly, 2009.
[3]     Goyvaerts, Jan.  Regular Expressions: The Complete Tutorial.
        https://www.regular-expressions.info/.
[4]     Python.org documentation: `re` module.
        https://docs.python.org/3/library/re.html
[5]     Kuchling, A.M.  "Regular Expression HOWTO."
        https://docs.python.org/3/howto/regex.html
[6]     Python.org documentation: `ipaddress` module.
        Copyright 2007 Google Inc.
        Licensed to PSF under a Contributor Agreement.
        https://docs.python.org/3/library/ipaddress.html
[7]     nerdsrescueme/regex.txt.
        https://gist.github.com/nerdsrescueme/1237767

Citations are included for "unique" regexes that are copied from a
singular source.  More "generic" regexes that can be found in
similar form from multiple public sources may not be cited here.
"""

__author__ = 'Brad Solomon <brad.solomon.1124@gmail.com>'
__license__ = 'MIT'

import functools
import re
from typing import Optional
from typing.re import Pattern  # < Python 3.6 support
import warnings

# ---------------------------------------------------------------------
# *Email address*.  Source: [3]

EMAIL = re.compile(r"\"*[a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&@'*+/=?^_`{|}~-]+)*\"*@(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", flags=re.I)
LOOSE_EMAIL = re.compile(r'\S+@\S+')

# ---------------------------------------------------------------------
# *Whitespace*

# 2+ consecutive of any whitespace
# \s --> ` \t\n\r\f\v`
MULT_WHITESPACE = re.compile(r'\s\s+')

# 2+ consecutive literal spaces, excluding other whitespace.
# Space is Unicode code-point 32.
MULT_SPACES = re.compile(r'  +')

# ---------------------------------------------------------------------
# *Grammar*

# A generic word tokenizer, defined as one or more alphanumeric characters
# bordered by word boundaries
WORD = re.compile(r'\b\w+\b')

# Source: [4]
ADVERB = re.compile(r'\w+ly')


def not_followed_by(word: str) -> Pattern:
    return re.compile(r'\b\w+\b(?!\W+{word}\b)'.format(word=word))


def followed_by(word: str) -> Pattern:
    return re.compile(r'\b\w+\b(?=\W+{word}\b)'.format(word=word))


# ---------------------------------------------------------------------
# *Phone numbers*

# Restricted to follow the North American Numbering Plan (NANP),
#     a telephone numbering plan that encompasses 25 distinct
#     regions in twenty countries primarily in North America,
#     including the Caribbean and the U.S. territories.
# https://en.wikipedia.org/wiki/North_American_Numbering_Plan#Modern_plan
US_PHONENUM = re.compile(r'(?<!-)(?:\b|\+|)(?:1(?: |-|\.|\()?)?(?:\(?[2-9]\d{2}(?: |-|\.|\) |\))?)?[2-9]\d{2}(?: |-|\.)?\d{4}\b')

# E.164 ITU phone number format
# https://www.itu.int/rec/dologin_pub.asp?lang=e&id=T-REC-E.164-201011-I!!PDF-E&type=items
E164_PHONENUM = re.compile(r'\+?[1-9]\d{1,14}\b')
# ---------------------------------------------------------------------

# ---------------------------------------------------------------------
# *IP addresses*

# Unlike Python's ipaddress module, we are only concerned with
# string representations of IP addresses, not their integer or
# bytes representations.
#
# Definitions: https://docs.python.org/3/library/ipaddress.html

# Valid IPv4 address:  Source: [6]
#
# A string in decimal-dot notation, consisting of four decimal integers
# in the inclusive range 0–255, separated by dots (e.g. 192.168.0.1).
# Each integer represents an octet (byte) in the address. Leading zeroes
# are tolerated only for values less than 8 (as there is no ambiguity
# between the decimal and octal interpretations of such strings).
IPV4 = re.compile(r'\b(([0]{1,2}[0-7]|[0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])\.){3}([0]{1,2}[0-7]|[0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])\b')

# Valid IPv6 address:  Source:
# https://github.com/aio-libs/aiohttp/blob/master/aiohttp/helpers.py
#
# See also: RFC 3986
_ipv6 = (
    r'^(?:(?:(?:[A-F0-9]{1,4}:){6}|(?=(?:[A-F0-9]{0,4}:){0,6}'
    r'(?:[0-9]{1,3}\.){3}[0-9]{1,3}$)(([0-9A-F]{1,4}:){0,5}|:)'
    r'((:[0-9A-F]{1,4}){1,5}:|:)|::(?:[A-F0-9]{1,4}:){5})'
    r'(?:(?:25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])\.){3}'
    r'(?:25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])|(?:[A-F0-9]{1,4}:){7}'
    r'[A-F0-9]{1,4}|(?=(?:[A-F0-9]{0,4}:){0,7}[A-F0-9]{0,4}$)'
    r'(([0-9A-F]{1,4}:){1,7}|:)((:[0-9A-F]{1,4}){1,7}|:)|(?:[A-F0-9]{1,4}:){7}'
    r':|:(:[A-F0-9]{1,4}){7})$')
IPV6 = re.compile(_ipv6, re.I)

# ---------------------------------------------------------------------
# *URLs*

# Valid Uniform Resource Locator (URL) as prescribed by RFC 1738
# http://www.ietf.org/rfc/rfc1738.txt
STRICT_URL = re.compile(r'\b(?:https?|ftp|file)://[-A-Z0-9+&@#/%?=~_|$!:,.;]*[A-Z0-9+&@#/%=~_|$]', re.I)
LOOSE_URL = re.compile(r'\b(?:(?:https?|ftp|file)://|(?:www|ftp)\.)[-A-Z0-9+&@#/%?=~_|$!:,.;]*[A-Z0-9+&@#/%=~_|$]', re.I)

# IANA root-zone database country-code domains
# https://www.iana.org/domains/root/db
_domains = (
    '.ac', '.ad', '.ae', '.af', '.ag', '.ai', '.al', '.am', '.an',
    '.ao', '.aq', '.ar', '.as', '.at', '.au', '.aw', '.ax', '.az',
    '.ba', '.bb', '.bd', '.be', '.bf', '.bg', '.bh', '.bi', '.bj',
    '.bl', '.bm', '.bn', '.bo', '.bq', '.br', '.bs', '.bt', '.bv',
    '.bw', '.by', '.bz', '.ca', '.cc', '.cd', '.cf', '.cg', '.ch',
    '.ci', '.ck', '.cl', '.cm', '.cn', '.co', '.cr', '.cu', '.cv',
    '.cw', '.cx', '.cy', '.cz', '.de', '.dj', '.dk', '.dm', '.do',
    '.dz', '.ec', '.ee', '.eg', '.eh', '.er', '.es', '.et', '.eu',
    '.fi', '.fj', '.fk', '.fm', '.fo', '.fr', '.ga', '.gb', '.gd',
    '.ge', '.gf', '.gg', '.gh', '.gi', '.gl', '.gm', '.gn', '.gp',
    '.gq', '.gr', '.gs', '.gt', '.gu', '.gw', '.gy', '.hk', '.hm',
    '.hn', '.hr', '.ht', '.hu', '.id', '.ie', '.il', '.im', '.in',
    '.io', '.iq', '.ir', '.is', '.it', '.je', '.jm', '.jo', '.jp',
    '.ke', '.kg', '.kh', '.ki', '.km', '.kn', '.kp', '.kr', '.kw',
    '.ky', '.kz', '.la', '.lb', '.lc', '.li', '.lk', '.lr', '.ls',
    '.lt', '.lu', '.lv', '.ly', '.ma', '.mc', '.md', '.me', '.mf',
    '.mg', '.mh', '.mk', '.ml', '.mm', '.mn', '.mo', '.mp', '.mq',
    '.mr', '.ms', '.mt', '.mu', '.mv', '.mw', '.mx', '.my', '.mz',
    '.na', '.nc', '.ne', '.nf', '.ng', '.ni', '.nl', '.no', '.np',
    '.nr', '.nu', '.nz', '.om', '.pa', '.pe', '.pf', '.pg', '.ph',
    '.pk', '.pl', '.pm', '.pn', '.pr', '.ps', '.pt', '.pw', '.py',
    '.qa', '.re', '.ro', '.rs', '.ru', '.rw', '.sa', '.sb', '.sc',
    '.sd', '.se', '.sg', '.sh', '.si', '.sj', '.sk', '.sl', '.sm',
    '.sn', '.so', '.sr', '.ss', '.st', '.su', '.sv', '.sx', '.sy',
    '.sz', '.tc', '.td', '.tf', '.tg', '.th', '.tj', '.tk', '.tl',
    '.tm', '.tn', '.to', '.tp', '.tr', '.tt', '.tv', '.tw', '.tz',
    '.ua', '.ug', '.uk', '.um', '.us', '.uy', '.uz', '.va', '.vc',
    '.ve', '.vg', '.vi', '.vn', '.vu', '.wf', '.ws', '.ಭಾರತ', '.한국',
    '.ଭାରତ', '.ভাৰত', '.ভারত', '.বাংলা', '.қаз', '.срб', '.бг',
    '.бел', '.சிங்கப்பூர்', '.мкд', '.ею', '.中国', '.中國', '.భారత్',
    '.ලංකා', '.ભારત', '.भारतम्', '.भारत', '.भारोत', '.укр', '.香港',
    '.台湾', '.台灣', '.мон', '\u200f.الجزائر\u200e', '\u200f.عمان\u200e',
    '\u200f.ایران\u200e', '\u200f.امارات\u200e',
    '\u200f.موريتانيا\u200e', '\u200f.پاکستان\u200e',
    '\u200f.الاردن\u200e', '\u200f.بارت\u200e', '\u200f.بھارت\u200e',
    '\u200f.المغرب\u200e', '\u200f.السعودية\u200e',
    '\u200f.ڀارت\u200e', '\u200f.سودان\u200e', '\u200f.عراق\u200e',
    '\u200f.مليسيا\u200e', '.澳門', '.გე', '.ไทย', '\u200f.سورية\u200e',
    '.рф', '\u200f.تونس\u200e', '.ελ', '.ഭാരതം', '.ਭਾਰਤ',
    '\u200f.مصر\u200e', '\u200f.قطر\u200e', '.இலங்கை', '.இந்தியா',
    '.հայ', '.新加坡', '\u200f.فلسطين\u200e', '.ye', '.yt', '.za', '.zm',
    '.zw'
)

# Hinge on the presence of a domain, and be liberal about
# what comes before it.
LOOSE_URL_DOMAIN = re.compile(
    r'\b\S+' + '(?:{})'.format("|".join(_domains)) + r'\S*\b')

# ---------------------------------------------------------------------
# *Numbers and currency*

# All currency symbols in the {Sc} category (Symbol, currency)
# Source: http://www.fileformat.info/info/unicode/category/Sc/list.htm
MONEYSIGN = (u'\u0024\u00A2\u00A3\u00A4\u00A5\u058F\u060B\u09F2\u09F3'
             u'\u09FB\u0AF1\u0BF9\u0E3F\u17DB\u20A0\u20A1\u20A2\u20A3'
             u'\u20A4\u20A5\u20A6\u20A7\u20A8\u20A9\u20AA\u20AB\u20AC\u20AD'
             u'\u20AE\u20AF\u20B0\u20B1\u20B2\u20B3\u20B4\u20B5\u20B6\u20B7'
             u'\u20B8\u20B9\u20BA\u20BB\u20BC\u20BD\u20BE\u20BF\uA838\uFDFC'
             u'\uFE69\uFF04\uFFE0\uFFE1\uFFE5\uFFE6')

# For the lexical structure for a "number," we steal from the Postgres
# docs, with a few additions:
#
#     Numeric constants are accepted in these general forms:
#
#     digits
#     digits.[digits][e[+-]digits]
#     [digits].digits[e[+-]digits]
#     digitse[+-]digits
#
#     where digits is one or more decimal digits (0 through 9).
#     At least one digit must be before or after the decimal point,
#     if one is used. At least one digit must follow the exponent marker
#     (e), if one is present.  Brackets indicate optionality.
#
# To this, we add the optionality to use commas and allow or disallow
# leading zeros.
#
# Four different variations of a "number" regex based on whether
# we want to allow leading zeros and/or commas.
# Thanks @WiktorStribiżew for the lookahead:
# https://stackoverflow.com/a/50223631/7954504

_number_combinations = {
    (True, True): (
        # Leading zeros permitted; commas permitted.
        r'(?:(?<= )|(?<=^))(?<!\.)\d+(?:,\d{3})*(?= |$)',
        r'(?:(?<= )|(?<=^))(?<!\.)\d+(?:,\d{3})*\.\d+(?:[eE][+-]?\d+)?(?= |$)',
        r'(?:(?<= )|(?<=^))(?<!\d)\.\d+(?:[eE][+-]?\d+)?(?= |$)'
        ),
    (True, False): (
        # Leading zeros permitted; commas not permitted.
            r'(?:(?<= )|(?<=^))(?<!\.)\d+(?= |$)',
            r'(?:(?<= )|(?<=^))(?<!\.)\d+\.\d+(?:[eE][+-]?\d+)?(?= |$)',
            r'(?:(?<= )|(?<=^))(?<!\d)\.\d+(?:[eE][+-]?\d+)?(?= |$)'
        ),
    (False, True): (
        # Leading zeros not permitted; commas permitted.
            r'(?:(?<= )|(?<=^))(?<!\.)[1-9]+\d*(?:,\d{3})*(?= |$)',
            r'(?:(?<= )|(?<=^))(?<!\.)[1-9]+\d*(?:,\d{3})*\.\d+(?:[eE][+-]?\d+)?(?= |$)',
            r'(?:(?<= )|(?<=^))(?<!\d)\.\d+(?:[eE][+-]?\d+)?(?= |$)'
        ),
    (False, False): (
        # Neither permitted.
            r'(?:(?<= )|(?<=^))(?<!\.)[1-9]+\d*(?= |$)',
            r'(?:(?<= )|(?<=^))(?<!\.)[1-9]+\d*\.\d+(?:[eE][+-]?\d+)?(?= |$)',
            r'(?:(?<= )|(?<=^))(?<!\d)\.\d+(?:[eE][+-]?\d+)?(?= |$)'
        )
    }


class Number(object):
    """A regex to match a wide syntax for 'standalone' numbers.

    "Number" is an inclusive term covering:
    - "Integers": 12, 1,234, 094,509.
    - "Decimals": 12.0, .5, 4., 12,000.00
    - Scientific notation: 12.0e-03, 1E-5

    The class instance is a compiled regex.

    Parameters
    ----------
    allow_leading_zeros: bool, default True
        Permit leading zeros on numbers.  (I.e. 042, 095,000, 09.05)
    allow_commas: bool, default True
        If True, allow *syntactically correct* commas.  (I.e. 1,234.09)
    flags: {int, enum.IntFlag}, default 0
        Passed to `re.compile()`.

    Returns
    -------
    Pattern, the object produced by `re.compile()`
    """

    def __new__(
        cls,
        allow_leading_zeros: bool = True,
        allow_commas: bool = True,
        flags=0
    ) -> Pattern:
        key = allow_leading_zeros, allow_commas
        pattern = '|'.join(_number_combinations[key])
        return re.compile(pattern, flags=flags)


class Integer(object):
    def __new__(
        cls,
        allow_leading_zeros: bool = True,
        allow_commas: bool = True,
        flags=0
    ) -> Pattern:
        key = allow_leading_zeros, allow_commas
        # The only difference here is we use 0th element only.
        pattern = _number_combinations[key][0]
        return re.compile(pattern, flags=flags)


class Decimal(object):
    def __new__(
        cls,
        allow_leading_zeros: bool = True,
        allow_commas: bool = True,
        flags=0
    ) -> Pattern:
        key = allow_leading_zeros, allow_commas
        # 0th element is for Integer; other are for Decimal.
        pattern = '|'.join(_number_combinations[key][1:])
        return re.compile(pattern, flags=flags)


# ---------------------------------------------------------------------
# *Geographic info*

# Five digits with optional 4-digit extension
# https://en.wikipedia.org/wiki/ZIP_Code#ZIP+4
US_ZIPCODE = re.compile(r'\b[0-9]{5}(?:-[0-9]{4})?\b(?!-)')

# Source: [7]
US_STATE = re.compile(r'\b(A[KLRZ]|C[AOT]|D[CE]|FL|GA|HI|I[ADLN]|K[SY]|LA|M[ADEINOST]|N[CDEHJMVY]|O[HKR]|PA|RI|S[CD]|T[NX]|UT|V[AT]|W[AIVY])\b')

# U.S. address - street name portion.
# This will not include city/state/ZIP
_roads = r'(?:' + '|'.join((
    r'Ave\.?',
    r'Avenue',
    r'Blvd\.?',
    r'Boulevard',
    r'Circle',
    r'Cr\.?',
    r'Court',
    r'Crossing',
    r'Dr\.?',
    r'Drive',
    r'Expressway',
    r'Freeway',
    r'Lane',
    r'Ln\.?',
    r'Parkway',
    r'Pkwy\.?',
    r'Place',
    r'Pl\.?',
    r'Rd\.?',
    r'Road',
    r'St\.?',
    r'Street',
    r'Terrace',
    r'Turnkpike',
    r'Way'
)) + r')'

_cardinal = r'(?: (?:N|S|E|W|NW|SW|NE|SE|East|West|North(?:west|east)?|South(?:west|east)?)\b)?'

# Parts of the actual address, in 99% of cases, will be either:
# - digits (223 Park Lane)
# - capitalized alphachars (223 Park Lane)
# - led by digits (503 47th St)
# There is not other reliable way to constrain the match, so we disallow
# words starting with lowercase.
_addrname = r'(?:(?:\d|[A-Z])\S* )+'
US_ADDRESS = re.compile(_addrname + _roads + _cardinal)

# ---------------------------------------------------------------------
# *PII*
# Please use these tools for benevolent purposes.

_pw = r'(?:p(?:ass)?w(?:ord)?|pword|passphrase|secret key|pass(?:wd)?)'
_un = r'(?:user(?:name)?|uname)'


def make_userinfo_re(start: str, flags=re.I) -> Pattern:
    return re.compile(start + r'(?:\s*[:=]\s*|\s+is\s+)(?P<token>\S+)',
                      flags=flags)


PASSWORD = make_userinfo_re(start=_pw)
USERNAME = make_userinfo_re(start=_un)


def _extract(s: str, *, r: Pattern = None) -> list:
    if not r:
        raise ValueError('`r` must not be null')
    return r.findall(s)


def _make_extract_info_func(start: str, flags=re.I):
    r = make_userinfo_re(start=start, flags=flags)
    return functools.partial(_extract, r=r)


extract_pw = _make_extract_info_func(start=_pw)
extract_un = _make_extract_info_func(start=_un)

# Social security numbers: AAA-GG-SSSS
# https://www.ssa.gov/history/ssn/geocard.html
STRICT_SSN = re.compile(r'\d{3}-\d{2}-\d{4}')
LOOSE_SSN = re.compile(r'\d{3}[ -]?\d{2}[ -]?\d{4}')

# Credit cards
_mastercard_start = r'\b(?:5[1-5][0-9]{2}|222[1-9]|22[3-9][0-9]|2[3-6][0-9]{2}|27[01][0-9]|2720)'
_cards = dict(
    _new_visa=r'\b4\d{3}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}',  # 4XXX-XXXX-XXXX-XXXX
    _old_visa=r'\b4\d{3}[ -]?\d{3}[ -]?\d{3}[ -]?\d{3}',  # 4XXX-XXX-XXX-XXX
    _mastercard=_mastercard_start + r'[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}',  # 5[1-5]XX-XXXX-XXXX-XXXX or [2221-2720]-XXXX-XXXX-XXXX
    _amex=r'3[47]\d{2}[ -]?\d{6}[ -]?\d{5}',  # 3[47]XX XXXXXX XXXXX
    _discover=r'6(?:011|5\d{2})[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}',  # 6011-XXXX-XXXX-XXXX or 65XX-XXXX-XXXX-XXXX
)

# Visa, Mastercard, Amex, Discover
STRICT_CREDIT_CARD = re.compile(r'|'.join(_cards.values()))
LOOSE_CREDIT_CARD = re.compile(r'[0-9-]{13,20}')

US_PASSPORT = re.compile(r'\b[C\d]\d{5,8}\b', re.I)

# Forked directly from:
# https://github.com/adambullmer/USDLRegex/blob/master/regex.json
# https://ntsi.com/drivers-license-format/
_license_by_state = {
    'AK': re.compile(r'\b[0-9]{1,7}\b', re.I),
    'AL': re.compile(r'\b[0-9]{1,7}\b', re.I),
    'AR': re.compile(r'\b[0-9]{4,9}\b', re.I),
    'AZ': re.compile(r'(?:\b[A-Z]{1}[0-9]{1,8}\b)|(?:\b[A-Z]{2}[0-9]{2,5}\b)|(?:\b[0-9]{9}\b)', re.I),
    'CA': re.compile(r'\b[A-Z]{1}[0-9]{7}\b', re.I),
    'CO': re.compile(r'(?:\b[0-9]{9}\b)|(?:\b[A-Z]{1}[0-9]{3,6}\b)|(?:\b[A-Z]{2}[0-9]{2,5}\b)', re.I),
    'CT': re.compile(r'\b[0-9]{9}\b', re.I),
    'DC': re.compile(r'(?:\b[0-9]{7}\b)|(?:\b[0-9]{9}\b)', re.I),
    'DE': re.compile(r'\b[0-9]{1,7}\b', re.I),
    'FL': re.compile(r'\b[A-Z]{1}[0-9]{12}\b', re.I),
    'GA': re.compile(r'\b[0-9]{7,9}\b', re.I),
    'GU': re.compile(r'\b[A-Z]{1}[0-9]{14}\b', re.I),
    'HI': re.compile(r'(?:\b[A-Z]{1}[0-9]{8}\b)|(?:\b[0-9]{9}\b)', re.I),
    'IA': re.compile(r'\b([0-9]{9}|(?:[0-9]{3}[A-Z]{2}[0-9]{4}))\b', re.I),
    'ID': re.compile(r'(?:\b[A-Z]{2}[0-9]{6}[A-Z]{1}\b)|(?:\b[0-9]{9}\b)', re.I),
    'IL': re.compile(r'\b[A-Z]{1}[0-9]{11,12}\b', re.I),
    'IN': re.compile(r'(?:\b[A-Z]{1}[0-9]{9}\b)|(?:\b[0-9]{9,10}\b)', re.I),
    'KS': re.compile(r'(?:\b([A-Z]{1}[0-9]{1}){2}[A-Z]{1}\b)|(?:\b[A-Z]{1}[0-9]{8}\b)|(?:\b[0-9]{9}\b)', re.I),
    'KY': re.compile(r'(?:\b[A_Z]{1}[0-9]{8,9}\b)|(?:\b[0-9]{9}\b)', re.I),
    'LA': re.compile(r'\b[0-9]{1,9}\b', re.I),
    'MA': re.compile(r'(?:\b[A-Z]{1}[0-9]{8}\b)|(?:\b[0-9]{9}\b)', re.I),
    'MD': re.compile(r'\b[A-Z]{1}[0-9]{12}\b', re.I),
    'ME': re.compile(r'(?:\b[0-9]{7,8}\b)|(?:\b[0-9]{7}[A-Z]{1}\b)', re.I),
    'MI': re.compile(r'(?:\b[A-Z]{1}[0-9]{10}\b)|(?:\b[A-Z]{1}[0-9]{12}\b)', re.I),
    'MN': re.compile(r'\b[A-Z]{1}[0-9]{12}\b', re.I),
    'MO': re.compile(r'(?:\b[A-Z]{1}[0-9]{5,9}\b)|(?:\b[A-Z]{1}[0-9]{6}[R]{1}\b)|(?:\b[0-9]{8}[A-Z]{2}\b)|(?:\b[0-9]{9}[A-Z]{1}\b)|(\b[0-9]{9}\b)', re.I),
    'MS': re.compile(r'\b[0-9]{9}\b', re.I),
    'MT': re.compile(r'(?:\b[A-Z]{1}[0-9]{8}\b)|(?:\b[0-9]{13}\b)|(?:\b[0-9]{9}\b)|(?:\b[0-9]{14}\b)', re.I),
    'NC': re.compile(r'\b[0-9]{1,12}\b', re.I),
    'ND': re.compile(r'(?:\b[A-Z]{3}[0-9]{6}\b)|(?:\b[0-9]{9}\b)', re.I),
    'NE': re.compile(r'\b[0-9]{1,7}\b', re.I),
    'NH': re.compile(r'\b[0-9]{2}[A-Z]{3}[0-9]{5}\b', re.I),
    'NJ': re.compile(r'\b[A-Z]{1}[0-9]{14}\b', re.I),
    'NM': re.compile(r'\b[0-9]{8,9}\b', re.I),
    'NV': re.compile(r'(?:\b[0-9]{9,10}\b)|(?:\b[0-9]{12}\b)|(?:\b[X]{1}[0-9]{8}\b)', re.I),
    'NY': re.compile(r'(?:\b[A-Z]{1}[0-9]{7}\b)|(?:\b[A-Z]{1}[0-9]{18}\b)|(?:\b[0-9]{8}\b)|(?:\b[0-9]{9}\b)|(?:\b[0-9]{16}\b)|(?:\b[A-Z]{8}\b)', re.I),
    'OH': re.compile(r'(?:\b[A-Z]{1}[0-9]{4,8}\b)|(?:\b[A-Z]{2}[0-9]{3,7}\b)|(?:\b[0-9]{8}\b)', re.I),
    'OK': re.compile(r'(?:\b[A-Z]{1}[0-9]{9}\b)|(?:\b[0-9]{9}\b)', re.I),
    'OR': re.compile(r'\b[0-9]{1,9}\b', re.I),
    'PA': re.compile(r'\b[0-9]{8}\b', re.I),
    'PR': re.compile(r'(?:\b[0-9]{9}\b)|(?:\b[0-9]{5,7}\b)', re.I),
    'RI': re.compile(r'\b(?:[0-9]{7}\b)|(?:\b[A-Z]{1}[0-9]{6}\b)', re.I),
    'SC': re.compile(r'\b[0-9]{5,11}\b', re.I),
    'SD': re.compile(r'(?:\b[0-9]{6,10}\b)|(?:\b[0-9]{12}\b)', re.I),
    'TN': re.compile(r'\b[0-9]{7,9}\b', re.I),
    'TX': re.compile(r'\b[0-9]{7,8}\b', re.I),
    'UT': re.compile(r'\b[0-9]{4,10}\b', re.I),
    'VA': re.compile(r'(?:\b[A-Z]{1}[0-9]{8,11}\b)|(?:\b[0-9]{9}\b)', re.I),
    'VT': re.compile(r'(?:\b[0-9]{8}\b)|(?:\b[0-9]{7}[A]\b)', re.I),
    'WA': re.compile(r'\b(?=.{12}\b)[A-Z]{1,7}[A-Z0-9\\*]{4,11}\b', re.I),
    'WI': re.compile(r'\b[A-Z]{1}[0-9]{13}\b', re.I),
    'WV': re.compile(r'(?:\b[0-9]{7}\b)|(?:\b[A-Z]{1,2}[0-9]{5,6}\b)', re.I),
    'WY': re.compile(r'\b[0-9]{9,10}\b', re.I)
}


def extract_us_drivers_license(
    s: str,
    state: Optional[str] = None
) -> tuple:
    if state:
        return _license_by_state[state.upper()].findall(s)
    else:
        res = set()
        add = res.add
        for state, regex in _license_by_state.items():
            matches = regex.findall(s)
            if matches:
                for i in matches:
                    add(i)
        return re


# ---------------------------------------------------------------------
# *Dates & times*

_dob = r'd(?:ate )?o(?:f )?b(?:irth)??'
DOB = make_userinfo_re(start=_dob)
extract_dob = _make_extract_info_func(start=_dob)

# ---------------------------------------------------------------------


class _DeprecatedRegex(object):
    """Warn about deprecated expressions, but keep their functionality."""
    def __init__(self, regex: Pattern, old: str, new=str.upper):
        if callable(new):
            new = new(old)
        self.msg = '\nThe `{old}` constant has been renamed `{new}` and is deprecated.  Use:\n\n\t>>> from re101 import {new}\n'.format(old=old, new=new)
        self.regex = regex
        self.old = old
        self.new = new

    def __getattr__(self, name):
        """Call __getattr__ for the newly-named Pattern."""
        if 'name' in {'old' 'new', 'regex', 'msg'}:
            return getattr(self, name)
        warnings.warn(self.msg, FutureWarning, stacklevel=2)
        return eval(self.new).__getattribute__(name)


email = _DeprecatedRegex(regex=EMAIL, old='email')
mult_whitespace = _DeprecatedRegex(regex=MULT_WHITESPACE, old='mult_whitespace')
mult_spaces = _DeprecatedRegex(regex=MULT_SPACES, old='mult_spaces')
word = _DeprecatedRegex(regex=WORD, old='word')
adverb = _DeprecatedRegex(regex=ADVERB, old='adverb')
ipv4 = IPv4 = _DeprecatedRegex(regex=IPV4, old='ipv4')
moneysign = _DeprecatedRegex(regex=MONEYSIGN, old='moneysign')

zipcode = _DeprecatedRegex(regex=US_ZIPCODE, old='zipcode', new='US_ZIPCODE')
state = _DeprecatedRegex(regex=US_STATE, old='state', new='US_STATE')
nanp_phonenum = _DeprecatedRegex(regex=US_PHONENUM, old='state', new='US_PHONENUM')

# Functions, classes that make Patterns with __new__(), and constants
# ---------------------------------------------------------------------
__all__ = (
    'not_followed_by',
    'followed_by',
    'Number',
    'Integer',
    'Decimal',
    'extract_pw',
    'extract_un',
    'extract_dob',
    'extract_us_drivers_license'
)
# Bring uppercase constants into the namespace.
_locals = locals()
__all__ = __all__ + tuple(
    i for i in _locals if i.isupper() and not i.startswith('_'))
del _locals
