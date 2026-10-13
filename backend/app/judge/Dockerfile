FROM gcc:14.2.0-bookworm@sha256:b99b86a28812b1e6453a231a947dc43d76fe192788a12f344a9b568bf9f5d24c

RUN apt-get update \
    && apt-get install --no-install-recommends -y python3 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 judge \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin judge \
    && mkdir -p /opt/judge \
    && chown root:root /opt/judge \
    && chmod 0555 /opt/judge

COPY --chown=root:root container_runner.py /opt/judge/runner.py
RUN chmod 0444 /opt/judge/runner.py

USER 10001:10001
WORKDIR /
