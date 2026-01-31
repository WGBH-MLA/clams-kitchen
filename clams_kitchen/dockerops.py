"""Docker operations for CLAMS Kitchen.

This module provides Docker container lifecycle management functions
for running CLAMS apps in both CLI and HTTP modes.
"""

import platform
import subprocess
import time

import requests


def get_docker_command_prefix() -> tuple:
    """Get Docker binary path and command prefix based on OS.

    Returns:
        Tuple of (docker_bin_path, coml_prefix)
    """
    current_os = platform.system()
    if current_os == "Windows":
        docker_bin_path = "/mnt/c/Program Files/Docker/Docker/resources/bin/docker"
        coml_prefix = ["bash"]
    elif current_os == "Linux":
        docker_bin_path = "/usr/bin/docker"
        coml_prefix = []
    else:
        raise OSError(f"Unsupported operating system: {current_os}")

    return docker_bin_path, coml_prefix


def add_volume_mounts(coml: list, cf: dict) -> list:
    """Add standard volume mounts to Docker command.

    Args:
        coml: Docker command list to append to
        cf: Configuration dictionary with volume mount paths

    Returns:
        Updated command list
    """
    if cf["media_required"]:
        coml += ["-v", cf["shell_media_dir"] + '/:/data']
    if cf["shell_cache_dir"]:
        coml += ["-v", cf["shell_cache_dir"] + '/:/cache']
    if cf["shell_config_dir"]:
        coml += ["-v", cf["shell_config_dir"] + '/:/app/config']
    return coml


def start_clams_http_container(image: str, cf: dict, gpus: str = None) -> tuple:
    """Start a CLAMS app container as an HTTP server.

    The container runs Flask in debug mode (app.py --debug) for full logging.
    Container is intended to be reused across all batch items.

    Args:
        image: Docker image name
        cf: Configuration dictionary with volume mount paths
        gpus: GPU configuration (e.g., "all") or None

    Returns:
        Tuple of (container_id, host_port, container_name)
    """
    docker_bin_path, coml_prefix = get_docker_command_prefix()

    # Extract container name from image (last path component + tag)
    # Example: "ghcr.io/clamsproject/app-swt-detection:v8.4" -> "app-swt-detection:v8.4"
    image_parts = image.split('/')
    container_name = image_parts[-1]

    # Build docker run command for HTTP server mode
    coml = [
        docker_bin_path,
        "run",
        "-d",                    # Detached mode
        "--rm",                  # Remove on stop
        "--name", container_name,  # Named container for easy identification
        "-p", "5000",            # Expose port 5000 (Docker assigns host port)
        "-v", cf["shell_mmif_dir"] + '/:/mmif'
    ]

    # Add standard volume mounts
    coml = add_volume_mounts(coml, cf)

    if gpus:
        coml += ["--gpus", gpus]

    # Add image and entry point for Flask debug server
    coml.append(image)
    coml += ["python", "app.py", "--debug"]

    coml = coml_prefix + coml

    # Start the container
    result = subprocess.run(coml, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to start container: {result.stderr}")

    container_id = result.stdout.strip()

    # Get the assigned host port
    port_cmd = coml_prefix + [docker_bin_path, "port", container_id, "5000"]
    result = subprocess.run(port_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        # Cleanup and raise
        subprocess.run(coml_prefix + [docker_bin_path, "stop", container_id],
                       capture_output=True)
        raise RuntimeError(f"Failed to get container port: {result.stderr}")

    # Parse port from output like "0.0.0.0:49153" or ":::49153"
    port_str = result.stdout.strip().split(":")[-1]
    host_port = int(port_str)

    return container_id, host_port, container_name


def wait_for_container_ready(port: int, timeout: int = 120, interval: float = 2.0) -> bool:
    """Wait for the CLAMS HTTP server to be ready.

    Args:
        port: Host port mapped to container's port 5000
        timeout: Maximum seconds to wait
        interval: Seconds between polling attempts

    Returns:
        True when ready

    Raises:
        TimeoutError: If server not ready within timeout
    """
    start_time = time.time()
    url = f"http://localhost:{port}/"

    while time.time() - start_time < timeout:
        try:
            # Try a simple GET request to check if server is up
            response = requests.get(url, timeout=5)
            # Any response (even 405 Method Not Allowed) means server is up
            return True
        except requests.exceptions.ConnectionError:
            # Server not ready yet
            time.sleep(interval)
        except requests.exceptions.Timeout:
            # Server not responding
            time.sleep(interval)

    raise TimeoutError(f"Container HTTP server not ready after {timeout} seconds")


def stop_clams_http_container(container_id: str) -> None:
    """Stop and remove a CLAMS HTTP server container.

    Args:
        container_id: Docker container ID
    """
    docker_bin_path, coml_prefix = get_docker_command_prefix()

    # Stop the container (--rm flag will auto-remove it)
    stop_cmd = coml_prefix + [docker_bin_path, "stop", container_id]
    result = subprocess.run(stop_cmd, capture_output=True, text=True)

    # Don't raise on error - container might already be stopped
    if result.returncode != 0:
        print(f"Warning: Container stop returned non-zero: {result.stderr}")


def capture_container_logs(container_id: str, output_prefix: str,
                           start_time: str, end_time: str) -> None:
    """Capture container logs for a specific time window.

    Uses docker logs with --since and --until flags to capture stdout/stderr
    from the container during request processing.

    Args:
        container_id: Docker container ID
        output_prefix: Base path for output files (without extension)
        start_time: ISO timestamp for --since flag
        end_time: ISO timestamp for --until flag

    Output files:
        {output_prefix}.out - Container stdout (gunicorn access logs, app output)
        {output_prefix}.err - Container stderr (gunicorn errors, warnings)
    """
    docker_bin_path, coml_prefix = get_docker_command_prefix()

    # Build docker logs command with time window
    logs_cmd = coml_prefix + [
        docker_bin_path, "logs",
        "--since", start_time,
        "--until", end_time,
        container_id
    ]

    result = subprocess.run(logs_cmd, capture_output=True, text=True)

    # Write stdout if present
    if result.stdout:
        stdout_path = f"{output_prefix}.out"
        with open(stdout_path, "w") as f:
            f.write(result.stdout)
        print(f"    Container stdout saved to: {stdout_path}")

    # Write stderr if present
    if result.stderr:
        stderr_path = f"{output_prefix}.err"
        with open(stderr_path, "w") as f:
            f.write(result.stderr)
        print(f"    Container stderr saved to: {stderr_path}")

    if not result.stdout and not result.stderr:
        print("    No container logs captured for this request.")
