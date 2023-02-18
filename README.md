<div align="center">
   <img src="https://user-images.githubusercontent.com/50381946/219900824-088508fe-49c6-4365-9bc4-53759d9c1aa3.png" width="96" height="96"><br>
   <img src="https://user-images.githubusercontent.com/50381946/219900788-6f308c76-1808-4906-a4e5-9a1f323a53cc.png" width="400" height="64">
</div>

<div align="center">
  <img src="https://img.shields.io/badge/python-3.8-3776AB?logo=python&logoColor=white&labelColor=333333">
</div>
<h1> </h1>



A Slack bot and set of scripts for exporting history (and something more) from public channels, private channels and direct messages (DMs), using Slack's new Conversations API.

A similar service is provided by Slack for workspace admins at [https://my.slack.com/services/export](https://my.slack.com/services/export) (where `my` can be replaced with your full workspace name to refer to a workspace different than your default). However, it can only access public channels, while `pyslacker` can retrieve data from any channel accessible to your user account.

Based on [sebseager/slack-exporter](https://github.com/sebseager/slack-exporter)

## Authentication with Slack

There are two ways to use `pyslacker` (detailed below). Both require a Slack API token to be able to communicate with your workspace.

1. Visit [https://api.slack.com/apps/](https://api.slack.com/apps/) and sign in to your workspace.
2. Click `Create New App`, enter a name (e.g., `Slack Exporter`), and select your workspace.
3. In prior versions of the Slack API, OAuth permissions had to be specified manually. Now, when prompted for an App Manifest, just paste in the contents of the `slack.yaml` file in the root of this repo.
4. Select `Install to Workspace` at the top of that page (or `Reinstall to Workspace` if you have done this previously) and accept at the prompt.
5. Copy the `OAuth Access Token` (which will generally start with `xoxp` for user-level permissions)

## Usage

### As a script

Wrapper script `dump-history.sh` can create an archive of all accessible conversation history with all replies in your workspace.

1. Either add

    ```text
    SLACK_USER_TOKEN = xoxp-xxxxxxxxxxxxx...
    ```

   to a file named `.env` in repo's root (run `cp .env.dist .env` if it doesn't exist) or run the following in your shell (replacing the value with the user token you obtained in the [Authentication with Slack](#authentication-with-slack) section above).

    ```shell script
    export SLACK_USER_TOKEN=xoxp-xxxxxxxxxxxxx...
    ```

2. Run `./warmup-cache.sh`. This script will download and cache channels and users from your workspace (this step is optional, but recommended).
3. Type all channels you want to save as comma-separated list and run: `./dump-history.sh channel1,channel2`;
4. ... or run `./dump-history-from-json.sh` which will use `channel.json` in repo's root as a source of channels to export (run `cp channel.dist.json channel.json` if file doesn't exist and add channels to copied file). If you skipped step 2, channel/user lists will be downloaded before actual export starts, but this needs to be done only once.

#### Tips

* `dump-emoji.sh` can be used to download all emojis defined in a workspace (but as for now it requires some additional manual work).
* To interact with history export script directly, use: `venv/bin/python -m pyslacker --help` (this will list available options).

### As a Slack bot

`pyslacker/bot.py` is a Slack bot that responds to "slash commands" in Slack channels (e.g., `/export-channel`). To connect the bot to the Slack app generated in [Authentication with Slack](#authentication-with-slack), add the following line to a file named `.env` in repo's root (run `cp .env.dist .env` if it doesn't exist) :

```text
SLACK_USER_TOKEN = xoxp-xxxxxxxxxxxxx...
``` 

After that run the Flask app such that the application is exposed to the Internet. This can be done via a web server (e.g., Heroku), as well as via the ngrok service, which assigns your `localhost` server a public URL.

To use the ngrok method:

1. [Download](https://ngrok.com/download) the appropriate binary.
2. Run `./start-bot.sh`
3. Run the ngrok binary with `path/to/ngrok http 5000`, where `5000` is the port on which the Flask application (step 2) is running. Copy the forwarding HTTPS address provided.

4. Create the following slash commands will be created (one for each applicable Flask route):

   | Command         | Request URL                               | Arguments    | Example Usage        |
   |-----------------|-------------------------------------------|--------------|----------------------|
   | /export-channel | https://`[host_url]`/slack/export-channel | json \| text | /export-channel text |
   | /export-replies | https://`[host_url]`/slack/export-replies | json \| text | /export-replies json |

   To do this, clone `slack.dist.yaml` as `slack.yaml`, uncomment the `slash-commands` section in `slack.yaml` and replace `YOUR_HOST_URL_HERE` with something like `https://xxxxxxxxxxxx.ngrok.io` (if using ngrok). Then navigate back to `OAuth & Permissions` and click `(Re)install to Workspace` to add these slash commands to the workspace (ensure the OAuth token in your `.env` file is still correct).

## Screenshots

Example of channel history export completed in 186 requests (all thumbnails are clickable):

<img src="doc/screen1.png" alt="screenshot" width="66%">

Running wrapper script with two channels specified:

<img src="doc/screen2.png" alt="screenshot" width="66%">

Running preparation script <code>warmup-cache.sh</code> which downloads full channel list and full user list. This is optional, because these lists will be loaded anyway before actual export starts; but in that case this will be done within export command, which might be confusing.

<img src="doc/screen3.png" alt="screenshot" width="66%"> 

## Contributors

* [Seb Seager](https://github.com/sebseager) (original scripts)
* [Aleksandr Shavykin](https://github.com/delameter) (refactoring, detailed output, more exporters)
* [Mikhail Shipov](https://github.com/SkReD) (enchancements, fixes)

## License

This software is available under the [GPL](LICENSE).
