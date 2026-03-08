/*
 * Launcher binary for "iCloud Sync.app".
 * Discovers the bundled Python at runtime so the .app can be installed
 * anywhere without recompiling.
 *
 * Path layout (relative to this binary at Contents/MacOS/<name>):
 *   ../Resources/venv/bin/python3          — bundled Python interpreter
 *   ../Resources/venv/bin/icloud-sync-tray — tray app entry-point script
 *
 * The tray script's shebang is intentionally ignored; we exec Python
 * directly with the script as its first argument.
 *
 * Compiled by build_app.sh — do not run directly.
 */
#include <errno.h>
#include <fcntl.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syslimits.h>
#include <unistd.h>

int main(int argc, char *argv[]) {
    /* ── Resolve this executable's real path ──────────────────────────── */
    char exec_buf[PATH_MAX];
    uint32_t exec_size = sizeof(exec_buf);
    if (_NSGetExecutablePath(exec_buf, &exec_size) != 0) {
        fprintf(stderr, "launcher: _NSGetExecutablePath failed\n");
        return 1;
    }
    char exec_path[PATH_MAX];
    if (!realpath(exec_buf, exec_path)) {
        fprintf(stderr, "launcher: realpath(%s): %s\n", exec_buf, strerror(errno));
        return 1;
    }

    /* ── Navigate to Contents/ ────────────────────────────────────────── */
    /* exec_path: .../Contents/MacOS/<AppName>  */
    char *slash = strrchr(exec_path, '/');
    if (!slash) { fprintf(stderr, "launcher: unexpected path: %s\n", exec_path); return 1; }
    *slash = '\0';  /* → .../Contents/MacOS */
    slash = strrchr(exec_path, '/');
    if (!slash) { fprintf(stderr, "launcher: unexpected path: %s\n", exec_path); return 1; }
    *slash = '\0';  /* → .../Contents */

    /* ── Build paths into the bundled venv ───────────────────────────── */
    char python[PATH_MAX];
    char tray_script[PATH_MAX];
    snprintf(python,      sizeof(python),      "%s/Resources/venv/bin/python3",             exec_path);
    snprintf(tray_script, sizeof(tray_script), "%s/Resources/venv/bin/icloud-sync-tray",    exec_path);

    /* ── Redirect stdout+stderr to a log file ────────────────────────── */
    int fd = open("/tmp/icloud-sync-launch.log",
                  O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd >= 0) {
        dprintf(fd, "launcher: python=%s\n",      python);
        dprintf(fd, "launcher: script=%s\n",      tray_script);
        dup2(fd, STDOUT_FILENO);
        dup2(fd, STDERR_FILENO);
        close(fd);
    }

    /* ── Launch ──────────────────────────────────────────────────────── */
    char *args[] = { python, tray_script, NULL };
    execv(python, args);

    /* execv only returns on failure */
    fprintf(stderr, "launcher: execv(%s): %s\n", python, strerror(errno));
    return 1;
}
