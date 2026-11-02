# Troubleshooting

| What you see | What to do |
|---|---|
| Python could not be set up automatically | Check your internet connection and open the launcher again. If it still stops, install Python 3.13 with the [standard installer](https://www.python.org/downloads/release/python-31317/), then open the launcher again. On Windows, **Install Now** with default options is enough. |
| Windows says it protected your PC | This can appear for a downloaded `start.bat`. Choose **More info**, then **Run anyway**, if you downloaded it from this project. |
| Mac says it cannot verify `start.command` | Open **System Settings → Privacy & Security** and choose **Open Anyway**, if you downloaded it from this project. You can also open Terminal in the folder and run `bash start.sh`. |
| Windows reports an unsupported platform | Use Windows 10 or 11 on an x64 computer with 64-bit Python. Windows on ARM is not supported. |
| Mac reports an unsupported platform | Use macOS 14 or later on Apple silicon with native Apple silicon Python. An Intel Python under Rosetta is not supported. This release does not support Intel Macs. |
| Setup is taking a long time | First installation downloads several GB. Keep the window open while it reports progress. Check `.venv/setup.log` for details. |
| A download failed or disk space is low | Restore internet access and allow about 15 GB free, including on your system drive. Restart the launcher; completed package downloads can be reused. |
| Setup is already running | Return to the first setup window. Do not run two installers in the same folder. |
| An old environment shares packages or needs repair | Stop this app, rename `.venv` to `.venv-old`, then run the launcher. Keep the old folder until the new installation works. Both names are excluded from Git. Do not reuse another project's environment. |
| The browser did not open | Wait for the launcher to print the local address, then paste that exact address into a browser on this computer. |
| Local app unavailable | Keep the launcher window open. If it was closed, start it again and retry; refresh the page if its old document session expired. |
| Preparing local search failed | Check internet access and free space in your user cache, then choose Retry preparation. Completed files are reused. Closing just the page does not stop a running preparation. |
| First search is slow | The search files must be loaded into memory once per app process. Keep the app open; later searches reuse them. On less powerful computers this can take longer. |
| A long manuscript takes several minutes | Elapsed time remains visible. The app processes smaller portions sequentially to reduce memory use. Keep it open, or cancel waiting and try a single section. A GPU is optional; 16 GB RAM is recommended for comfortable manuscript use. |
| CLI installation not found | Install the selected CLI using the link in Model settings, sign in, then return to the page or choose Check again now. Reopen this app after a new CLI installation so it sees the updated PATH. |
| CLI needs an update | Use the agent's official update instructions, then return to the page. The app needs the isolation flags offered by current CLI releases. |
| Installed but not signed in | Run `codex login`, or run `claude` and use `/login`, in a terminal. Return here and test the connection. |
| Allowance reached or access denied | Check your subscription/account and the chosen model. Wait for the allowance to reset or select another model you can access. |
| API key rejected | Replace the key from the same provider's developer console. Check API billing/access separately from any chat subscription. Never paste keys into issue reports. |
| Model list unavailable | Some endpoints do not offer a model list. Enter a chat model ID from that provider's console, check the base URL, then test. |
| Empty or invalid model reply | Check the model and API base URL; choose a chat-capable model. A connection test needs a usable reply, not just an HTTP success status. |
| Section identification failed | Your current manuscript and previous section choices remain available. Correct model settings and retry. If the file expired after 30 minutes, choose it again. |
| PDF contains no readable text | Use a text-based PDF, Word or plain-text file. Scanned PDFs need text recognition before use. |
| DOI not found | The bundled collection does not contain every article from its seven journals. The DOI page lists what it covers. Choose **Paste a section instead** and paste the abstract or another section to compare the paper anyway. |

## Storage and privacy

The app environment is in the extracted repository's `.venv`. Search files normally use your user cache (`~/.cache/huggingface`); package downloads and temporary files may use the system drive. First setup and preparation need internet access. Once prepared, similarity retrieval does not need an external service.

Cloud models receive the extracted manuscript only when you choose Identify sections. Uploaded files are removed after local extraction; extracted text remains temporarily in application memory. Keys are not written to application logs. Model cancellation stops the local request, but a provider may still count work already processed.

Before sharing a diagnostic, remove manuscript content, usernames, file paths, credentials and account identifiers. Report the operating system, Python version, app version, step that failed, and the relevant error message. Never include `.env`, `auth.json`, agent configuration folders or a complete virtual environment.
