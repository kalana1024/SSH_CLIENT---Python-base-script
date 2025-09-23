import argparse
import logging
import paramiko
import sys
from typing import Optional

# Hexdump function for debugging binary output
def hexdump(src: bytes, length: int = 16) -> str:
    result = []
    for i in range(0, len(src), length):
        s = src[i:i + length]
        hexa = ' '.join(f"{x:02X}" for x in s)
        text = ''.join(chr(x) if 0x20 <= x < 0x7F else '.' for x in s)
        result.append(f"{i:04X}   {hexa:<{length * 3}}   {text}")
    return '\n'.join(result)

# Execute SSH command and return output
def ssh_command(
    ip: str,
    user: str,
    passwd: Optional[str] = None,
    key_file: Optional[str] = None,
    command: str = "id",
    port: int = 22,
    timeout: float = 10.0,
    verbose_hexdump: bool = False
) -> tuple[str, str, int]:
   
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        # Connect to SSH server
        client.connect(
            hostname=ip,
            port=port,
            username=user,
            password=passwd,
            key_filename=key_file,
            timeout=timeout
        )
        
        # Execute command
        logging.info(f"Executing command: {command} on {ip}:{port}")
        stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        
        # Read output
        stdout_data = stdout.read()
        stderr_data = stderr.read()
        exit_code = stdout.channel.recv_exit_status()
        
        # Log output
        if stdout_data:
            logging.info(f"stdout:\n{stdout_data.decode('utf-8', errors='replace')}")
            if verbose_hexdump:
                logging.debug(f"stdout hexdump:\n{hexdump(stdout_data)}")
        if stderr_data:
            logging.warning(f"stderr:\n{stderr_data.decode('utf-8', errors='replace')}")
            if verbose_hexdump:
                logging.debug(f"stderr hexdump:\n{hexdump(stderr_data)}")
        
        return stdout_data.decode('utf-8', errors='replace'), stderr_data.decode('utf-8', errors='replace'), exit_code
    
    except paramiko.AuthenticationException as e:
        logging.error(f"Authentication failed: {e}")
        return "", str(e), 1
    except paramiko.SSHException as e:
        logging.error(f"SSH error: {e}")
        return "", str(e), 1
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        return "", str(e), 1
    finally:
        client.close()
        logging.debug("SSH client connection closed.")

def main():
    parser = argparse.ArgumentParser(description="Advanced SSH Client with Paramiko")
    parser.add_argument("ip", help="SSH server IP address (e.g., 192.168.100.131)")
    parser.add_argument("user", help="SSH username")
    parser.add_argument("--password", help="SSH password (use with caution)")
    parser.add_argument("--key-file", help="Path to SSH private key file")
    parser.add_argument("--command", default="id", help="Command to execute (default: id)")
    parser.add_argument("--port", type=int, default=22, help="SSH server port (default: 22)")
    parser.add_argument("--timeout", type=float, default=10.0, help="Timeout for command execution in seconds (default: 10.0)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging (INFO level)")
    parser.add_argument("--debug-hexdump", action="store_true", help="Enable hexdump logging for output (DEBUG level)")
    parser.add_argument("--log-file", help="Log output to this file")

    args = parser.parse_args()

    # Set up logging
    log_level = logging.DEBUG if args.debug_hexdump else (logging.INFO if args.verbose else logging.WARNING)
    logging.basicConfig(level=log_level, format="[%(asctime)s] %(levelname)s: %(message)s")

    if args.log_file:
        file_handler = logging.FileHandler(args.log_file)
        file_handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s"))
        logging.getLogger().addHandler(file_handler)

    # Validate authentication method
    if not args.password and not args.key_file:
        parser.error("Either --password or --key-file must be provided for authentication.")

    # Execute SSH command
    stdout, stderr, exit_code = ssh_command(
        ip=args.ip,
        user=args.user,
        passwd=args.password,
        key_file=args.key_file,
        command=args.command,
        port=args.port,
        timeout=args.timeout,
        verbose_hexdump=args.debug_hexdump
    )

    # Exit with appropriate status code
    sys.exit(exit_code)

if __name__ == "__main__":
    main()