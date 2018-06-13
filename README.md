# kakoune-ghci-bridge

An experimental wrapper around ghci to get Haskell intellisense in the [Kakoune](https://github.com/mawwww/kakonue) editor,
inspired by [jyp](https://github.com/jyp)'s emacs mode [dante](https://github.com/jyp/dante).
A notable exception is that it only loads exactly the saved files in the project rather than making virtual files for unsaved files.

## setup

Run `python bridge.py SESSION DIR GHCI_CMD`

This connects with the kak session using a command for `ghci` (for example `cabal repl`) starting in the directory `DIR`.
When running you see some debug output and inside kakoune you get a bunch of commands prefixed with `ghci-`.
It also populates the `user` keymap with some bindings.



    def start-ghci-bridge -params 0..1 -docstring '
        start-ghci-bridge [GHCI_CMD]

        Starts the bridge.py using the GHCI_CMD, default "make ghci"
    ' %{
        %sh{
            dir=$PWD
            cd ~/code/kakoune-ghci-bridge
            (
                python bridge.py "$kak_session" "$dir" "${1:-make ghci}"
            ) > /dev/null 2>&1 < /dev/null &
        }
    }

## todo

Completion suggesions.

## Background and implementation

Since GHC 8.0.1 ghci has the commands `:type-at`, `:loc-at` and `:uses`
(enabled by `:set +c`), implemented by [Chris Done](https://github.com/chrisdone), see [phabricator](https://phabricator.haskell.org/D1240), [ghc trac](https://ghc.haskell.org/trac/ghc/ticket/10873).
The kakoune communication technique is a slimmed-down version of [libkak](https://github.com/danr/libkak).
Future work include transforming this into a [language server](https://microsoft.github.io/language-server-protocol/),
perhaps built on top of [ghcid](https://github.com/ndmitchell/ghcid), see [#138](https://github.com/ndmitchell/ghcid/issues/138).

## License

MIT
