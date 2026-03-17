# Btool Check for Splunk

A Splunk app that wraps the `splunk btool check` CLI command as a custom search command. Identify typos and invalid keys in your `.conf` files directly from the Splunk search bar.

## Why?

Splunk Cloud customers cannot access the CLI to run `splunk btool check`. This app brings that functionality into the search bar so you can validate your configuration files without needing CLI access.

## Installation

1. Download the `TA_btool_check_<version>.tar.gz` package from [Releases](https://github.com/rephillips/splunk_btool_check/releases)
2. In Splunk Web, go to **Apps > Manage Apps > Install app from file**
3. Upload the `.tar.gz` file and restart Splunk when prompted

## Usage

### Check all configuration files

```
| btoolcheck
```

### Filter results to a specific conf file

```
| btoolcheck conf=savedsearches
```

### Scope the check to a specific app

```
| btoolcheck app=Splunk_TA_windows
```

### Combine both filters

```
| btoolcheck conf=props app=Splunk_TA_windows
```

## Output Fields

| Field | Description |
|-------|-------------|
| `message_type` | Type of issue: "Invalid key", "Possible typo", or "No spec file" |
| `stanza` | The stanza name where the issue was found |
| `file_path` | Full path to the `.conf` file |
| `line_number` | Line number in the conf file |
| `key_name` | The invalid or misspelled key name |
| `value` | The value associated with the key |
| `app_name` | Splunk app name extracted from the file path |
| `conf_file_name` | The conf file type (e.g., "savedsearches", "props") |

## Example Searches

Find all issues grouped by app:

```
| btoolcheck | stats count by app_name message_type
```

Find issues in a specific app:

```
| btoolcheck | search app_name="my_custom_app"
```

Show only invalid keys (exclude typos and info messages):

```
| btoolcheck | search message_type="Invalid key"
```

## Requirements

- Splunk Enterprise or Splunk Cloud 8.x, 9.x, or 10.x
- Admin or sc_admin role (or a role with the `run_btool_check` capability)

## Permissions

The `btoolcheck` command requires the `run_btool_check` capability, which is granted to the `admin` and `sc_admin` roles by default. To grant access to other roles, add the capability in **Settings > Access Controls > Roles**.

## Notes

- `btool check` is a global operation — it does not support `--app` or per-conf-file arguments.
- Both the `conf=` and `app=` parameters work by filtering the output of the global check. The app name is extracted from the file path in each line of output.

## License

Apache License 2.0
