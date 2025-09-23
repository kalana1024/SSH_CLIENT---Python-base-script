Features:

SSH Command Execution:

Executes a specified command on a remote SSH server and retrieves its stdout, stderr, and exit code.

Supports both password-based and key-based authentication.

Logging and Debugging:

Verbose logging (INFO level) for command execution and errors.

Hexdump logging (DEBUG level) for detailed binary output when enabled.

Logs stdout and stderr of the executed command, with options to log them as hexadecimal for debugging.

SSH Configuration:

Allows you to specify the SSH port (default is 22).

Supports SSH timeout for command execution, with a default of 10 seconds.

Authentication:

Can use either an SSH password (--password) or an SSH private key file (--key-file) for authentication.

Command Customization:

The default command to execute is id, but you can specify any command with the --command option.

Logging to File:

Option to log output to a specified file (--log-file).

Commands and Arguments:

Basic Options:

ip: SSH server IP address (e.g., 192.168.100.131).

user: SSH username.

--password: SSH password for authentication.

--key-file: Path to SSH private key file for authentication.

--command: Command to execute on the remote host (default is id).

--port: SSH server port (default is 22).

--timeout: Command execution timeout in seconds (default is 10.0).

Logging Options:

--verbose, -v: Enable verbose logging (INFO level).

--debug-hexdump: Enable hexdump for output debugging (DEBUG level).

--log-file: Log output to the specified file.

Authentication Requirements:

Password or Key File: You must provide either --password or --key-file for authentication.

Example Usage:

Execute a command using password authentication:

python3 ssh_client.py 192.168.100.131 user --password mypassword --command "ls -l"


Execute a command using SSH key-based authentication:

python3 ssh_client.py 192.168.100.131 user --key-file /path/to/keyfile --command "uptime"


Enable verbose logging and hexdump for debugging:

python3 ssh_client.py 192.168.100.131 user --password mypassword --command "df -h" --verbose --debug-hexdump


This script provides a powerful SSH client with detailed logging and debugging options, making it ideal for secure remote command execution and troubleshooting.
