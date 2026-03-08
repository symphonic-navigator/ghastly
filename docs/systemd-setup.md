# Running ghastly as a systemd User Service

ghastly can run as a persistent background service using systemd's user instance,
so the dashboard stays live across terminal sessions and restarts automatically
on crash.

## Setup

1. Copy the service file to the systemd user directory:

   ```sh
   mkdir -p ~/.config/systemd/user
   cp /path/to/ghastly/docs/ghastly.service ~/.config/systemd/user/ghastly.service
   ```

   If you installed via `pip` or `uv tool install`, you can download the service
   file directly:

   ```sh
   curl -o ~/.config/systemd/user/ghastly.service \
     https://raw.githubusercontent.com/PLACEHOLDER_OWNER/ghastly/main/docs/ghastly.service
   ```

2. Reload the systemd user daemon to pick up the new unit:

   ```sh
   systemctl --user daemon-reload
   ```

3. Enable and start the service:

   ```sh
   systemctl --user enable --now ghastly
   ```

4. Verify it is running:

   ```sh
   systemctl --user status ghastly
   ```

5. Follow live logs:

   ```sh
   journalctl --user -u ghastly -f
   ```

## Notes

- The service runs `ghastly` from `~/.local/bin/ghastly`. If you installed via
  a different method, adjust `ExecStart` in the service file accordingly.
- ghastly writes its own log file to `~/.local/share/ghastly/ghastly.log`
  regardless of systemd. The `journalctl` output captures stdout/stderr.
- To stop and disable the service:

  ```sh
  systemctl --user disable --now ghastly
  ```
