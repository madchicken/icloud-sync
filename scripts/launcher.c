/*
 * Launcher binary for "iCloud Sync.app".
 * Replaces the shell script so macOS will actually execute it when
 * the user double-clicks the icon (Gatekeeper rejects shell script
 * executables in unsigned .app bundles).
 *
 * The Python interpreter path and script path are baked in at compile
 * time via -DPYTHON_BIN and -DTRAY_SCRIPT preprocessor defines.
 *
 * Compiled by build_app.sh — do not run directly.
 */
#include <unistd.h>
#include <stdio.h>
#include <fcntl.h>
#include <errno.h>
#include <string.h>

int main(int argc, char *argv[]) {
    /* Redirect stdout+stderr to a log file so we capture Python errors */
    int fd = open("/tmp/icloud-sync-launch.log",
                  O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd >= 0) {
        dprintf(fd, "launcher: python=%s\n", PYTHON_BIN);
        dprintf(fd, "launcher: script=%s\n", TRAY_SCRIPT);
        dup2(fd, STDOUT_FILENO);
        dup2(fd, STDERR_FILENO);
        close(fd);
    }

    char *args[] = { PYTHON_BIN, TRAY_SCRIPT, NULL };
    execv(PYTHON_BIN, args);

    /* execv only returns on failure */
    fprintf(stderr, "execv failed: %s\n", strerror(errno));
    return 1;
}
