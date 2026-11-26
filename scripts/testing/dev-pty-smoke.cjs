'use strict';
const assert = require('node:assert/strict');
const path = require('node:path');
const { createRequire } = require('node:module');
const root = process.argv[3];
const packageRequire = createRequire(path.join(process.argv[2], 'package.json'));
const pty = packageRequire('node-pty');
let output = '';
let resized = false;
let timedOut = false;
const terminal = pty.spawn('/bin/sh', ['-c', "printf 'PTY_SIZE_A='; stty size; printf 'PTY_READY\\n'; read reply; printf 'PTY_SIZE_B='; stty size; printf 'PTY_DONE\\n'"], {
  name: 'xterm-256color',
  cols: 80,
  rows: 24,
  cwd: root,
  env: { PATH: '/usr/bin:/bin', HOME: path.join(root, 'home'), TERM: 'xterm-256color', LANG: 'C.UTF-8' },
});
const deadline = setTimeout(() => { timedOut = true; terminal.kill(); }, 15000);
terminal.onData((data) => {
  output += data;
  if (!resized && output.includes('PTY_READY')) {
    resized = true;
    terminal.resize(100, 40);
    terminal.write('continue\r');
  }
});
terminal.onExit(({ exitCode, signal }) => {
  clearTimeout(deadline);
  try {
    assert.equal(timedOut, false, 'PTY deadline exceeded');
    assert.equal(exitCode, 0, 'shell exited unsuccessfully');
    assert.equal(resized, true, 'PTY was not resized');
    assert.match(output, /PTY_SIZE_A=24 80/);
    assert.match(output, /PTY_SIZE_B=40 100/);
    assert.match(output, /PTY_DONE/);
    console.log(JSON.stringify({ result: 'PASS', node: process.version, uid: process.getuid(), platform: process.platform, arch: process.arch, initialSize: [80, 24], resizedSize: [100, 40], exitCode, signal }));
  } catch (error) {
    console.error(JSON.stringify({ result: 'FAIL', error: error.message, output, exitCode, signal }));
    process.exitCode = 1;
  }
});
