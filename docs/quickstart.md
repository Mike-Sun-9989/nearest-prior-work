# First successful search

## 1. Install and open

You do not need to install Python. Use Windows 10 or 11 on an x64 computer, or an Apple silicon Mac with macOS 14 or later. See [platform requirements](platforms.md).


Download the repository ZIP with **Code → Download ZIP**, extract it completely into a normal folder, and open the folder containing `README.md`. Do not run the launcher from inside the ZIP. Allow about **15 GB free** for the app, search files and installation caches; some downloads use your system drive even if you extract elsewhere.

- Windows: double-click `start.bat`.
- Mac: double-click `start.command`. Use your normal user account.

A window opens and shows the setup stages, and your browser opens when they finish. Initial installation downloads several GB and can take several minutes or longer on a slow connection. Keep the window open. The address is usually `http://127.0.0.1:8800`; if that address is occupied, use the address printed in the window.

If a suitable Python (3.11–3.13) is already installed, the launcher uses it. Otherwise it downloads a private copy of about 25 MB into the `.runtime` folder inside the app and verifies its checksum. Deleting the app folder removes it.

## 2. Let local search prepare

The first time the page opens, it starts downloading the search files by itself (about 2.3 GB, once) and displays progress. You can complete model settings, preview your file and run DOI searches while it runs. Leave the app running until preparation finishes. If the connection drops, choose **Retry preparation** when connected again.

## 3. Connect your own language model

Open **Model settings** and choose one route. This model is used only to identify manuscript sections.

### Codex CLI subscription

1. Follow the [official CLI installation instructions](https://learn.chatgpt.com/docs/cli) if Codex CLI is not installed. Having a ChatGPT subscription alone does not install the CLI.
2. Open a terminal, run `codex login`, and sign in with the subscription account you intend to use. See [official authentication help](https://learn.chatgpt.com/docs/auth).
3. Return to this app. Choose **My AI subscription → Codex CLI**, and return to the page. It checks again by itself; **Check again now** does the same. If you just installed the CLI and it cannot be found, close and reopen this app.
4. Leave **Model** blank to use the agent default. Choose **Test connection**, wait for **Connection verified**, then **Use these settings**.

The connection test makes one small real model call. Section identification also uses your plan allowance. An installed/signed-in indicator alone is not a connection test.

### Claude Code subscription

Follow [Claude Code setup](https://code.claude.com/docs/en/setup), launch `claude` in a terminal and use `/login` to sign in. Choose **My AI subscription → Claude Code**, return to the page, test and use the settings as above.

### API key

1. Create a key in your provider's developer console and make sure the account has access to the model you want.
2. Choose **API key**, select the provider and enter the key. A subscription to a chat website does not automatically supply an API key or API credit.
3. Choose **Load available models**, then select a chat-capable model. If listing is unavailable, enter its exact model ID from the provider's console.
4. For **OpenAI-compatible endpoint**, enter the provider's API base URL in the visible address field. Use the base address, not a URL ending in `/chat/completions`.
5. Choose **Test connection**, then **Use these settings**. The test uses a small amount of API allowance.

Keys stay in page memory unless you separately select **Also save this API key in this browser**. Leave that unchecked on shared computers. **Clear saved settings** removes locally saved settings and keys.

### Local model

Start your local model service, choose **Local model**, and enter its address and an installed chat model. Test and use the settings. This route can keep section identification local as well.

## 4. Run the included example

1. Choose **Manuscript → Choose a manuscript** and select `examples/demo_manuscript.docx` from the extracted folder. The example is synthetic, with invented data and findings.
2. Review **Preview extracted text**. At this point no language-model call has been made.
3. Choose **Identify sections**. This sends the extracted text to your selected model. Wait for the section list; you can cancel a slow request without losing the file.
4. Expand headings to inspect their original text and review the assigned roles. Change a role or choose **Not compared** if needed. The example should have abstract, introduction, theory, method, results and discussion passages; model output may vary.
5. Once local preparation is complete, choose **Find similar articles**. The first search also loads the search files into memory, so it can take longer than later searches. Wait for **Search complete**.
6. Use **Find closest by** to search by a particular section. Choose **Export CSV** to download the current result order.

The homepage's **Try an example search** is a quicker indexed-article demonstration; it does not exercise manuscript identification or call your language model.

## 5. Use it again

Run the same launcher. It reuses a completed installation and opens an already-running copy when possible. Your search files are cached. Text and indexed-DOI retrieval work offline after preparation. Cloud CLI/API identification still needs a connection, and opening a DOI uses the publisher's website.

See [troubleshooting](troubleshooting.md) if any step stops.
