#!/usr/bin/env bash
echo "************ Configuring Trailarr Custom Scripts *************"

# Get Arr App information
if [ -z "$arrUrl" ] || [ -z "$arrApiKey" ]; then
    arrUrlBase="$(cat /config/config.xml | xq | jq -r .Config.UrlBase)"
if [ "$arrUrlBase" == "null" ]; then
    arrUrlBase=""
else
    arrUrlBase="/$(echo "$arrUrlBase" | sed "s/\///")"
fi
arrName="$(cat /config/config.xml | xq | jq -r .Config.InstanceName)"
arrApiKey="$(cat /config/config.xml | xq | jq -r .Config.ApiKey)"
arrPort="$(cat /config/config.xml | xq | jq -r .Config.Port)"
arrUrl="http://127.0.0.1:${arrPort}${arrUrlBase}"
fi

# Verify API access
until false
do
arrApiTest=""
arrApiVersion=""
if [ "$arrPort" == "8989" ] || [ "$arrPort" == "7878" ]; then
    arrApiVersion="v3"
elif [ "$arrPort" == "8686" ] || [ "$arrPort" == "8787" ]; then
    arrApiVersion="v1"
fi
arrApiTest=$(curl -s "$arrUrl/api/$arrApiVersion/system/status?apikey=$arrApiKey" | jq -r .instanceName)
if [ "$arrApiTest" == "$arrName" ]; then
    break
else
    echo "$arrName is not ready, sleeping until valid response..."
    sleep 1
fi
done


if curl -s "$arrUrl/api/v3/notification" -H "X-Api-Key: ${arrApiKey}" | jq -r .[].name | grep "Trailarr" | read; then
    echo "************ Trailarr already configured ************"
    sleep infinity
else
    echo "Adding Trailarr to custom scripts"
    # Send a command to check file path, to prevent error with adding...
    updateArr=$(curl -s "$arrUrl/api/v3/filesystem?path=%2Fconfig%2Fscripts%2FTrailarr%2Ftrailarr.py&allowFoldersWithoutTrailingSlashes=true&includeFiles=true" -H "X-Api-Key: ${arrApiKey}")
    
    # Add trailarr.py
    updateArr=$(curl -s "$arrUrl/api/v3/notification?" -X POST -H "Content-Type: application/json" -H "X-Api-Key: ${arrApiKey}" --data-raw '{"onGrab": false,"onDownload": true,"onUpgrade": true,"onRename": true,"onMovieAdded": false,"onMovieDelete": false,"onMovieFileDelete": true,"onMovieFileDeleteForUpgrade": false,"onHealthIssue": false,"onHealthRestored": false,"onApplicationUpdate": false,"onManualInteractionRequired": false,"supportsOnGrab": false,"supportsOnDownload": true,"supportsOnUpgrade": true,"supportsOnRename": true,"supportsOnMovieAdded": false,"supportsOnMovieDelete": false,"supportsOnMovieFileDelete": true,"supportsOnMovieFileDeleteForUpgrade": false,"supportsOnHealthIssue": false,"supportsOnHealthRestored": false,"supportsOnApplicationUpdate": false,"supportsOnManualInteractionRequired": false,"includeHealthWarnings": false,"name": "Trailarr","fields":[{"name":"path","value":"/config/scripts/Trailarr/trailarr.py"},{"name":"arguments"}],"implementationName":"Custom Script","implementation":"CustomScript","configContract":"CustomScriptSettings","infoLink":"https://wiki.servarr.com/radarr/supported#customscript","message":{"message":"Testing will execute the script with the EventType set to Test, ensure your script handles this correctly","type":"warning"},"tags":[]}')

    # Parse Error
    if printf "%s" "$updateArr" | jq -e 'if type=="array" then true else false end' > /dev/null; then
        error=$(printf "%s" "$updateArr" | jq -r .[0].errorMessage)
    else
        error=
    fi

    # Check for Sucess
    if [ -z "$error" ]; then
        echo "Script Configured Sucessfully"
        sleep infinity
        exit 0
    fi

    # Print Error Message
    if [ "$error" == "File does not exist" ]; then
        echo "Script not found, check that git has cloned the repo"
    elif [[ "$error" == *"Permission denied"* ]]; then
        echo "Script has incorrect permissions"
    elif [ ! -z "$error" ]; then
        echo "Script Test Failed"
    else
        echo "Unknown Error While configuring script"
    fi
    echo "Error: $error"
    echo "Trailarr was not configured properly"

fi

exit