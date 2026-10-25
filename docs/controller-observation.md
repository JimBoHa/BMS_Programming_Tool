# Observe a verified instance change

Run `python scripts/observe_controller.py /private/path/trial` from an installed
BMS Studio environment. This host utility reads the selected controller, its
keeper, router and explicitly discovered I/O once per minute for one hour. It
records five-minute checkpoints and fails on identity, I/O reliability or
operational-status changes. It sends no controller writes or backup/restore
commands. A completed observation is bounded evidence, not proof of every BAS
alarm or physical output.

Keep the entire trial directory outside source control. Required JSON inputs:

- `settings.json`: `controller`, `new_instance`, `keeper_name`, `io_objects`
  (BACnet object identifiers), and `target`, `keeper`, `router_target` objects
  containing the address, device identifier and optional router/DNET.
- `interface-before.json`: `config.local_address` supplies the local IPv4 host.
  The observer uses its own UDP port 47820 and client device ID 4190092; reserve
  these before starting alongside another BACnet client.
- `verified-change.json`: `status` must equal `verified`.

The output directory receives private samples, checkpoints and final status.
An exclusive `observation-once.json` marker prevents accidental restarts in an
existing trial. Use a fresh directory for another authorized observation.
The script remains a separate host utility; opening the app never starts it.
