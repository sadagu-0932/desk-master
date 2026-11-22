#!/bin/bash
export INTEGRATED_STUDIO_DATA=/tmp/claude-0/-home-user-desk-master/1a2ff5ac-4963-560d-ab8b-dc491f6b4d43/scratchpad/e2e/data
cd /home/user/desk-master/integrated-studio/applications/electron
exec xvfb-run -a -s "-screen 0 1440x900x24 +extension GLX +render -noreset" /home/user/desk-master/integrated-studio/node_modules/electron/dist/electron . "$1" --remote-debugging-port=9333 --no-sandbox
