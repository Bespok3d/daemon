# On-target (Python 3.11) daemon test image. The source is COPIED in (build context = the daemon repo
# root), NOT mounted, so mutmut's in-place mutation runs on the container's copy and never touches the
# host tree. This keeps the project's 3.11 toolchain entirely in Docker: nothing is installed on the
# dev machine.
FROM python:3.11-slim

# The daemon shells out to `patch` (instrumentation steps); slim images omit it.
RUN apt-get update && apt-get install -y --no-install-recommends patch && rm -rf /var/lib/apt/lists/*

WORKDIR /daemon
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt
COPY . .
