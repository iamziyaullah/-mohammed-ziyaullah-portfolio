#!/bin/sh
set -eu
exec sh "$(dirname "$0")/RUN-LOCAL.sh" --admin
