"""FRIDAY. A fully local, always-on ambient AI.

The authoritative document is `docs/spec/FRIDAY-final-spec.md`. Where any file in this
repository disagrees with the spec, the spec wins and the file is the bug. `docs/DECISIONS.md`
records the decisions the spec makes, implies, and that were made after it.

Three top-level packages, and the split between them is deliberate:

    friday      everything she is: memory, senses, voice, loops, tools
    scrutiny    spec section 4. Seven axes, five actions, ~200 lines
    supervisor  spec section 9. ~150 lines, a DIFFERENT USER, and it must not import
                friday.* or it inherits that code's surface area and its dependencies

Stubs in this package raise NotImplementedError with the contract and the week that
implements them. Never a plausible empty return: a function that returns `[]` lets a week
appear to pass its own test, and the phase guide's "done when" then certifies nothing.
"""

__version__ = "0.1.0"
