"""gem_report_draft/_cards.py -- the ONE canonical poker-hand display component (Wave-2, v8.18.0).

Before this, card markup was emitted independently by four+ call sites (_card_html/_cards_html in
_html.py, the villain-card span in _hand_grid.py, the popup .handcards JS, the review-queue JS). This
module is the SINGLE owner of: rank, suit, suit glyph, suit colour class, spacing, the accessible
label, the compact/standard/prominent size variants, and unknown/partial-card behaviour. Every Python
surface renders a hand through `render_poker_hand` (or the back-compat `card_html`/`cards_html`
shims that delegate here), and the client JS reads the same typed payload, so desktop and mobile use
the SAME semantic component and data -- no separate mobile hand-rendering logic.

Typed boundary (frozen, serialisable for a future web frontend):
    CardVM(rank, suit)   -> glyph, colour_class, unknown, label, render()
    HandVM(cards, size)  -> render()
    HandDisplaySize      -> COMPACT | STANDARD | PROMINENT
The DOM marker is `poker-hand` (the `_POKER_HAND_MARKER`); a bypass test asserts no migrated surface
hand-writes raw `<span class="card ...">` outside this owner.
"""
import html as _html
from enum import Enum
from dataclasses import dataclass, field

_POKER_HAND_MARKER = 'poker-hand'

# the ONE suit table (glyph + colour class + spoken name). Mirrors _html._SUIT_HTML so the existing
# .card.card-s/h/d/c CSS keeps colouring the pills -- one source, no second definition.
_SUIT = {
    's': ('♠', 'card-s', 'spades'),    # spades
    'h': ('♥', 'card-h', 'hearts'),    # hearts
    'd': ('♦', 'card-d', 'diamonds'),  # diamonds
    'c': ('♣', 'card-c', 'clubs'),     # clubs
}
_RANK_NAME = {'A': 'Ace', 'K': 'King', 'Q': 'Queen', 'J': 'Jack', 'T': 'Ten',
              '9': 'Nine', '8': 'Eight', '7': 'Seven', '6': 'Six', '5': 'Five',
              '4': 'Four', '3': 'Three', '2': 'Two'}
_RANK_VALUE = {'A': 14, 'K': 13, 'Q': 12, 'J': 11, 'T': 10, '9': 9, '8': 8,
               '7': 7, '6': 6, '5': 5, '4': 4, '3': 3, '2': 2}
_SUIT_VALUE = {'s': 4, 'h': 3, 'd': 2, 'c': 1}


class HandDisplaySize(Enum):
    COMPACT = 'compact'
    STANDARD = 'standard'
    PROMINENT = 'prominent'


@dataclass(frozen=True)
class CardVM:
    """One playing card. `rank` is 'A'..'2' (or '?' unknown); `suit` is 's/h/d/c' (or '' unknown)."""
    rank: str = '?'
    suit: str = ''

    @property
    def unknown(self):
        return self.rank in ('?', '') or self.suit not in _SUIT

    @property
    def glyph(self):
        return _SUIT.get(self.suit, ('', '', ''))[0]

    @property
    def colour_class(self):
        return _SUIT.get(self.suit, ('', 'card-x', ''))[1]

    @property
    def label(self):
        if self.unknown:
            return 'unknown card'
        return '%s of %s' % (_RANK_NAME.get(self.rank, self.rank), _SUIT[self.suit][2])

    def sort_key(self):
        return (_RANK_VALUE.get(self.rank, 0), _SUIT_VALUE.get(self.suit, 0))

    @classmethod
    def parse(cls, token):
        """Parse a 'Ah' / '7d' / 'Tc' token. Unknown/partial ('', '?', 'Xx') -> an unknown CardVM."""
        t = (token or '').strip()
        if len(t) < 2:
            return cls('?', '')
        rank = t[0].upper()
        suit = t[1].lower()
        if rank not in _RANK_VALUE or suit not in _SUIT:
            return cls('?', '')
        return cls(rank, suit)

    def to_dict(self):
        return {'rank': self.rank, 'suit': self.suit, 'glyph': self.glyph,
                'colour_class': self.colour_class, 'unknown': self.unknown, 'label': self.label}

    def render(self):
        """The ONE place a single-card pill is produced. Markdown viewers still get rank+glyph text."""
        if self.unknown:
            return '<span class="card card-x" aria-label="unknown card">??</span>'
        return ('<span class="card %s" aria-hidden="true">%s%s</span>'
                % (self.colour_class, _html.escape(self.rank), self.glyph))


@dataclass(frozen=True)
class HandVM:
    cards: tuple = ()
    size: HandDisplaySize = HandDisplaySize.STANDARD

    @property
    def label(self):
        vis = [c.label for c in self.cards if not c.unknown]
        return ', '.join(vis) if vis else 'hand not shown'

    def to_dict(self):
        return {'cards': [c.to_dict() for c in self.cards], 'size': self.size.value, 'label': self.label}

    def render(self, marker=True):
        inner = ' '.join(c.render() for c in self.cards)
        if not marker:
            return inner
        return ('<span class="%s phd-%s" role="img" aria-label="%s">%s</span>'
                % (_POKER_HAND_MARKER, self.size.value, _html.escape(self.label), inner))


def _tokens(cards):
    """Normalise list | 'AhKh' | 'Ah Kh' to a token list."""
    if not cards:
        return []
    if isinstance(cards, str):
        s = cards.strip()
        return s.split() if ' ' in s else [s[i:i + 2] for i in range(0, len(s), 2)]
    return list(cards)


def build_hand(cards, sort_desc=False, size=HandDisplaySize.STANDARD):
    vms = [CardVM.parse(t) for t in _tokens(cards) if t]
    if sort_desc:
        vms = sorted(vms, key=lambda c: c.sort_key(), reverse=True)
    return HandVM(tuple(vms), size)


def render_poker_hand(cards, size=HandDisplaySize.STANDARD, sort_desc=False, marker=True):
    """THE canonical poker-hand renderer. `size` may be a HandDisplaySize or its string value."""
    if isinstance(size, str):
        size = HandDisplaySize(size)
    return build_hand(cards, sort_desc=sort_desc, size=size).render(marker=marker)


# --- back-compat shims: existing call sites keep working but now route through the ONE owner. ---
def card_html(token):
    """Single-card pill (the _html._card_html replacement)."""
    return CardVM.parse(token).render() if token and len(str(token).strip()) >= 2 else (token or '')


def cards_html(cards, sort_desc=False):
    """Space-joined pills WITHOUT the poker-hand wrapper (for markdown headings / inline use --
    keeps the legacy output so the markdown whitelist + heading layout are unchanged)."""
    if not cards:
        return ''
    return render_poker_hand(cards, sort_desc=sort_desc, marker=False)
