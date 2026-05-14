#!/usr/bin/with-contenv bash
echo "************ Install Packages ************"
apk add -U --update --no-cache \
	git \
	python3 \
	py3-pip \
	ffmpeg \
	deno

echo "************ install python packages ************"
pip install --upgrade --no-cache-dir -U --break-system-packages \
	yq


echo "************ Setup Script Directory ************"
if [ ! -d /config/scripts ]; then
	mkdir -p /config/scripts
fi

echo "************ Download / Update Repo ************"
if [ -d /config/scripts/Trailarr ]; then
    git -C /config/scripts/Trailarr pull
else
    git clone https://github.com/jsaddiction/Trailarr.git /config/scripts/Trailarr
fi

echo "************ Install Script Dependencies ************"
pip install --upgrade pip --no-cache-dir --break-system-packages
# -U upgrades existing packages (otherwise pip leaves them at the installed
# version even if requirements.txt is unpinned). The runtime self-update in
# downloaders/ytdlp.py handles per-run yt-dlp bumps; this covers fresh
# installs and the "restart the container" escape hatch.
pip install -U -r /config/scripts/Trailarr/requirements.txt --no-cache-dir --break-system-packages

echo "************ Set Permissions ************"
chmod 777 -R /config/scripts/Trailarr

echo "************ Configuring Radarr *********"
if [ ! -d /custom-services.d ]; then
    mkdir -p /custom-services.d
fi

if [ -f /custom-services.d/config_radarr.sh ]; then
	rm -rf /custom-services.d/config_radarr
fi

echo "Download AutoConfig service..."
curl https://raw.githubusercontent.com/jsaddiction/Trailarr/main/installer/config_radarr.sh -o /custom-services.d/TrailarrAutoConfig
echo "Done"

exit