from __future__ import absolute_import
from __future__ import print_function
import sys
import os
import tempfile
import re
import pexpect
import pexpect.replwrap
import six
from subprocess import Popen, PIPE
import traceback
from pprint import pformat, pprint


def nub(xs):
    seen = set()
    ys = []
    for x in xs:
        r = repr(x)
        if r not in seen:
            ys.append(x)
            seen.add(r)
    return ys


def echo(msg, where):
    """
    where = info | docsclient | echo
    """
    if not msg:
        return ''
    msg = msg.rstrip()
    if where and where.startswith('info'):
        return where + ' ' + single_quoted(join(msg.split('\n')[0:20], '\n'))
    elif where == 'docsclient':
        tmp = tempfile.mktemp()
        open(tmp, 'wb').write(encode(msg))
        return """
            eval -no-hooks -try-client %opt[docsclient] %[
              edit! -scratch '*doc*'
              exec \%d|cat<space> {tmp}<ret>
              exec \%|fmt<space> - %val[window_width] <space> -s <ret>
              exec gg
              set buffer filetype rst
              try %[rmhl number_lines]
              %sh[rm {tmp}]
            ]""".format(tmp=tmp)
    else:
        return 'echo ' + single_quoted(msg.split('\n')[0])


def single_quote_escape(string):
    """
    Backslash-escape ' and \ in Kakoune style .
    """
    return string.replace("\\'", "\\\\'").replace("'", "\\'")


def single_quoted(string):
    u"""
    The string wrapped in single quotes and escaped in Kakoune style.

    https://github.com/mawww/kakoune/issues/1049

    >>> print(single_quoted(u"i'ié"))
    'i\\'ié'
    """
    return u"'" + single_quote_escape(string) + u"'"


def backslash_escape(cs, s):
    for c in cs:
        s = s.replace(c, "\\" + c)
    return s


def encode(s):
    """
    Encode a unicode string into bytes.
    """
    if isinstance(s, six.binary_type):
        return s
    elif isinstance(s, six.string_types):
        return s.encode('utf-8')
    else:
        raise ValueError('Expected string or bytes')


def decode(s):
    """
    Decode into a string (a unicode object).
    """
    if isinstance(s, six.binary_type):
        return s.decode('utf-8')
    elif isinstance(s, six.string_types):
        return s
    else:
        raise ValueError('Expected string or bytes')


def join(words, sep=u' '):
    """
    Join strings or bytes into a string, returning a string.
    """
    return decode(sep).join(decode(w) for w in words)


class dotdict(dict):
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__


def chunks(s):
    return re.split('\n(?=\S)', s)


def filename_position_and_message(s):
    m = re.match('(?P<filename>[^:]+):(?P<line>\d+):(?P<col>\d+): (?P<msg>[\s\S]*)', s.rstrip(), re.M)
    return dotdict(m and m.groupdict() or dict(msg=s))


def filename_and_location_range(s):
    m = re.match('(?P<filename>[^:]+):\((?P<line1>\d+),(?P<col1>\d+)\)-\((?P<line2>\d+),(?P<col2>\d+)\)', s)
    return m and dotdict(m.groupdict())


def linewise(p):
    return lambda s: [p(l) for l in re.split('\n+', s) if l]


def chunkwise(p):
    return lambda s: list(map(p, chunks(s)))


def start_ghci(ghci_cmd, log=lambda x: print('[GHCI]:', x)):
    p = pexpect.replwrap.REPLWrapper(ghci_cmd, ">", ":set prompt [PEXPECT_PROMPT>")
    p.run_command(":set prompt2 [PEXPECT_PROMPT+")

    def run(cmd):
        log('[SEND]: ' + cmd)
        res = p.run_command(cmd).replace('\r', '')
        log('[RECV]: ' + res)
        return res
    run(":set -fno-code")
    run(":set -fdefer-typed-holes")
    run(":set -fdefer-type-errors")
    run(":set -Wall")
    run(":set -Wno-missing-signatures")
    run(":set -Wwarn=missing-home-modules")
    run(":set +c")
    # log(p.run_command(":set -fno-diagnostics-show-caret"))

    def cmd(cmd, parser=lambda x: x):
        def _(*args):
            res = parser(run(cmd + ' ' + ' '.join(str(s) for s in args)))
            log('[PRSD]: ' + pformat(res))
            return res
        return _

    return dotdict(
        load=cmd(':load', chunkwise(filename_position_and_message)),
        typeAt=cmd(':type-at'),
        locAt=cmd(':loc-at', filename_and_location_range),
        uses=cmd(':uses', linewise(filename_and_location_range)),
        info=cmd(':info'),
        type=cmd(':type'),
    )


def parse_selection_desc(s):
    m = re.match('(?P<line1>\d+)\.(?P<col1>\d+),(?P<line2>\d+)\.(?P<col2>\d+)', s)
    return m and m.groups()


def select(*ds):
    return 'select ' + ':'.join(''.join((d.line1, '.', d.col1, ',', d.line2, '.', d.col2)) for d in ds)


def edit(filename):
    return 'edit ' + filename


def pipe(session, msg, client=None):
    if msg.strip():
        if client:
            name = tempfile.mktemp()
            with open(name, 'wb') as tmp:
                print('[SEND]:', msg)
                tmp.write(encode(msg))
            msg = 'eval -client {} "%sh`cat {}; rm {}`"'.format(client, name, name)
        p = Popen(['kak', '-p', session], stdin=PIPE)
        print('[SEND]:', msg)
        p.communicate(encode(msg))


def main():

    try:
        _, session, dir, ghci_cmd = sys.argv
    except ValueError:
        print('echo -debug "Need three arguments: SESSION DIR GHCI_CMD"')
        return

    os.chdir(dir)
    ghci = start_ghci(ghci_cmd)

    dir = tempfile.mkdtemp()
    fifo = os.path.join(dir, 'python')
    os.mkfifo(fifo)

    commands = []

    def cmd(f):
        commands.append(f)
        return f

    self = dotdict(warnings=[])

    @cmd
    def load(session, client, timestamp, bufname, buf_line_count):
        res = ghci.load(bufname)
        self.warnings = nub([w for w in res if 'filename' in w])
        for w in self.warnings:
            if int(w.line) > int(buf_line_count):
                w.line = buf_line_count
        self.warnings.sort(key=lambda m: (m.filename, m.line, m.col))
        flags = [str(timestamp), '1|  ']

        def col(w):
            if w.msg.startswith('warning'):
                return 'yellow'
            else:
                return 'red'
        flags += [str(m.line) + '|{' + col(m) + u'}\u2022 ' for m in self.warnings if m.filename == bufname]
        flag_value = single_quoted(':'.join(flags))
        msgs = [
            'try %{decl line-specs ghci_flags}',
            'set buffer=' + bufname + ' ghci_flags ' + flag_value,
            'try %{addhl window/ flag_lines default ghci_flags}',
        ]
        msg = '\n'.join(msgs)
        pipe(session, msg, client)

    @cmd
    def diagnostic(session, client, timestamp, bufname, buf_line_count, line='$kak_cursor_line', direction='$1', where='$2'):
        load(session, client, timestamp, bufname, buf_line_count)
        ws = [w for w in self.warnings if w.filename == bufname]
        prev = direction == 'prev'
        next = direction == 'next'
        if prev:
            ws.reverse()
        jump = prev or next

        msgs = []

        if jump:
            dest = None
            for w in ws:
                if w.line < line if prev else w.line > line:
                    dest = w
                    break
            if dest is None and len(ws) > 0:
                dest = ws[0]
            if dest:
                if bufname != w.filename:
                    msgs += ['edit ' + bufname]
                if dest.line != line:
                    msgs += [select(dotdict(line1=dest.line, col1=dest.col, line2=dest.line, col2=dest.col))]
                line = dest.line

        cursor_placement = None
        wmsgs = []
        for w in ws:
            if w.line == line:
                if cursor_placement is None:
                    cursor_placement = 'info -placement above -anchor ' + w.line + '.' + w.col
                wmsgs += [w.msg]

        msgs += [echo('\n\n'.join(wmsgs), where or cursor_placement)]
        msg = '\n'.join(msgs)
        pipe(session, msg, client)
        return

    @cmd
    def definition(session, client, timestamp, bufname, buf_line_count, sel='$kak_selection_desc'):
        load(session, client, timestamp, bufname, buf_line_count)
        d = ghci.locAt(bufname, *parse_selection_desc(sel))
        msg = edit(d.filename) + ';' + select(d)
        pipe(session, msg, client)

    @cmd
    def uses(session, client, timestamp, bufname, buf_line_count, sel='$kak_selection_desc'):
        load(session, client, timestamp, bufname, buf_line_count)
        ds = ghci.uses(bufname, *parse_selection_desc(sel))
        filenames = [d.filename for d in ds]
        filenames.sort(key=lambda name: (name == ds[0].filename, name == bufname))
        best = filenames[-1]
        ds = [d for d in ds if d.filename == best]
        msg = edit(best) + ';' + select(*ds)
        pipe(session, msg, client)

    @cmd
    def typeAt(session, client, timestamp, bufname, buf_line_count, sel='$kak_selection_desc', where='$1'):
        load(session, client, timestamp, bufname, buf_line_count)
        res = ghci.typeAt(bufname, *parse_selection_desc(sel))
        msg = echo(res, where)
        pipe(session, msg, client)

    @cmd
    def info(session, client, timestamp, bufname, buf_line_count, text='$kak_selection', where='$1'):
        load(session, client, timestamp, bufname, buf_line_count)
        msg = echo(ghci.info(text), where)
        pipe(session, msg, client)

    @cmd
    def type(session, client, timestamp, bufname, buf_line_count, text='$kak_selection', where='$1'):
        load(session, client, timestamp, bufname, buf_line_count)
        msg = echo(ghci.type(text), where)
        pipe(session, msg, client)

    for f in commands:
        args = (':' + ':'.join(f.__defaults__)) if f.__defaults__ else ''
        name = f.__name__
        pipe(session, 'def -allow-override -params .. ghci-{name} %(%sh(echo {name}:$kak_session:$kak_client:$kak_timestamp:$kak_bufname:$kak_buf_line_count{args} > {fifo}))'.format(**locals()))
    pipe(session, '''def -allow-override ghci-bindings-for-buffer %{
        map buffer user . ': ghci-definition<ret>'
        map buffer user u ': ghci-uses<ret>'
        map buffer user t ': ghci-diagnostic next<ret>'
        map buffer user n ': ghci-diagnostic prev<ret>'
        map buffer user e ': ghci-diagnostic<ret>'
        map buffer user i ': ghci-typeAt info<ret>'
        map buffer user h ': ghci-info info<ret>'
    }
    def -allow-override ghci-hook-bindings-for-buffer %{
        hook -group ghci global BufSetOption filetype=haskell ghci-bindings-for-buffer
    }
    ''')
    command_dict = dict(((f.__name__, f) for f in commands))
    while True:
        with open(fifo, 'r') as f:
            for line in f:
                try:
                    cmd_args = line.rstrip('\n').split(':')
                    print('[RECV]:', cmd_args)
                    cmd = cmd_args[0]
                    args = cmd_args[1:]
                    print(command_dict[cmd])
                    command_dict[cmd](*args)
                except Exception as e:
                    print(e)
                    traceback.print_exc()


def test_ghci_main():

    _, ghci_cmd = sys.argv

    ghci = start_ghci(ghci_cmd)
    print("ghci.load('Test.hs')")
    print(ghci.load('Test.hs'))
    print("ghci.typeAt('Test.hs', 3, 17, 3, 18)")
    print(ghci.typeAt('Test.hs', 3, 17, 3, 18))
    print("ghci.locAt('Test.hs', 3, 17, 3, 18)")
    print(ghci.locAt('Test.hs', 3, 17, 3, 18))
    print("ghci.uses('Test.hs', 3, 17, 3, 18)")
    print(ghci.uses('Test.hs', 3, 17, 3, 18))
    print("ghci.info('f')")
    print(ghci.info('f'))
    print("ghci.type('f')")
    print(ghci.type('f'))


if __name__ == '__main__':
    main()
