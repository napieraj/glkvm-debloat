FROM archlinux/archlinux:base

RUN mkdir -p /etc/pacman.d/hooks \
	&& ln -s /dev/null /etc/pacman.d/hooks/30-systemd-tmpfiles.hook

RUN echo 'Server = https://mirror.rackspace.com/archlinux/$repo/os/$arch' > /etc/pacman.d/mirrorlist \
	&& pacman-key --init \
	&& pacman-key --populate archlinux

# Two more names in this list had gone stale the same way, and CI found them
# one build at a time:
#
#   libjpeg          -> renamed. Arch ships libjpeg-turbo, which PROVIDES
#                       libjpeg; the bare name is not an installable target.
#                       Needed to build ustreamer from source further down.
#   python-periphery -> dropped from the Arch repos. It is genuinely used --
#                       kvmd/plugins/ugpio/pwm.py imports `from periphery import
#                       PWM` -- so it moves to testenv/requirements.txt and is
#                       installed with pip rather than removed.
#
# PKGBUILD:56 also names python-periphery and is left alone, for the same
# reason as openssl-1.1: that is the device's dependency list, not this
# container's.
#
# openssl-1.1 was in the list below until 2026-09-10, and is why `make testenv`
# could not build AT ALL: Arch has dropped the package, so pacman fails with
# `target not found: openssl-1.1` before installing anything. That is the
# second independent reason this suite had never run in CI -- the first was a
# branch filter naming a branch that does not exist.
#
# Nothing in this container needs it. Every openssl call in the tree invokes
# the plain `openssl` binary (api/system.py, the WebAuthn verifier). The only
# other mention is PKGBUILD:104, which is the DEVICE package's dependency list
# and is deliberately left alone: whether a unit needs 1.1 is a question about
# the firmware image, not about this container.
RUN pacman --noconfirm --ask=4 -Syy \
	&& pacman --needed --noconfirm --ask=4 -S \
		glibc \
		pacman \
		openssl \
	&& pacman-db-upgrade \
	&& pacman --noconfirm --ask=4 -Syu \
	&& pacman --needed --noconfirm --ask=4 -S \
		p11-kit \
		archlinux-keyring \
		ca-certificates \
		ca-certificates-mozilla \
		ca-certificates-utils \
	&& pacman -Syu --noconfirm --ask=4 \
	&& pacman -S --needed --noconfirm --ask=4 \
		base-devel \
		autoconf-archive \
		help2man \
		m4 \
		vim \
		git \
		libjpeg-turbo \
		libevent \
		libutil-linux \
		libbsd \
		python \
		python-pip \
		python-build \
		python-wheel \
		python-setuptools \
		python-tox \
		python-mako \
		python-yaml \
		python-aiohttp \
		python-aiofiles \
		python-async-lru \
		python-passlib \
		python-pyserial \
		python-setproctitle \
		python-psutil \
		python-netifaces \
		python-systemd \
		python-dbus \
		python-dbus-next \
		python-pygments \
		python-pam \
		python-pillow \
		python-xlib \
		python-mako \
		libxkbcommon \
		python-hidapi \
		python-ldap \
		python-zstandard \
		libgpiod \
		freetype2 \
		nginx-mainline \
		tesseract \
		tesseract-data-eng \
		tesseract-data-rus \
		ipmitool \
		socat \
		eslint \
		npm \
		shellcheck \
	&& (pacman -Sc --noconfirm || true) \
	&& rm -rf /var/cache/pacman/pkg/*

COPY testenv/requirements.txt requirements.txt
RUN pip install --break-system-packages -r requirements.txt

# https://stackoverflow.com/questions/57534295
WORKDIR /root
RUN npm install htmlhint -g \
	&& npm install pug \
	&& npm install pug-cli -g \
	&& npm install @babel/eslint-parser -g
WORKDIR /

ARG USTREAMER_MIN_VERSION
ENV USTREAMER_MIN_VERSION $USTREAMER_MIN_VERSION
RUN echo $USTREAMER_MIN_VERSION
RUN git clone https://github.com/pikvm/ustreamer \
	&& cd ustreamer \
	&& make WITH_PYTHON=1 PREFIX=/usr DESTDIR=/ install \
	&& cd - \
	&& rm -rf ustreamer

RUN mkdir -p \
		/etc/kvmd/{nginx,vnc} \
		/var/lib/kvmd/msd \
		/var/lib/kvmd/pst/data \
		/opt/vc/bin

COPY testenv/fakes/vcgencmd /usr/bin/
COPY testenv/fakes/sys /fake_sysfs/sys
COPY testenv/fakes/proc /fake_procfs/proc
COPY testenv/fakes/etc /fake_etc/etc

CMD /bin/bash
