/*
 * Copy many tracks off a Creative jukebox in ONE libnjb session.
 *
 * Opening and capturing the device once per track (as the gettr sample
 * does) makes the Zen Micro dock/undock for every file, which eventually
 * hangs its firmware. This keeps the device captured for the whole run.
 *
 * Usage: njb_bulkget [pause in ms between 1 MiB chunks]
 *
 * stdin:  one request per line: "<trackid>\t<size>\t<output path>"
 * stdout: "READY" once captured, then "OK <id>" or "ERR <id>" per request.
 *         libnjb's own diagnostics and battery changes go to stderr.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "libnjb.h"

#define CHUNK_SIZE 0x100000U /* libnjb asks the player for 1 MiB at a time */

static unsigned chunk_pause_ms;

/* Called after every block; pausing on a chunk boundary gives the player's
 * drive a rest before libnjb requests the next chunk. */
static int pace(u_int64_t sent, u_int64_t total, const char *buf, unsigned len,
                void *data)
{
  if (chunk_pause_ms && sent < total && sent % CHUNK_SIZE == 0)
    usleep(chunk_pause_ms * 1000);
  return 0;
}

static void log_battery(njb_t *njb)
{
  static int last = -2;
  int level = NJB_Get_Battery_Level(njb);

  if (level != last)
    fprintf(stderr, "battery %d%%, %s\n", level,
            NJB_Get_Battery_Charging(njb) == 1 ? "charging" : "not charging");
  last = level;
}

int main(int argc, char **argv)
{
  njb_t njbs[NJB_MAX_DEVICES], *njb;
  char line[8192];
  FILE *reply;
  int n;

  if (argc > 1)
    chunk_pause_ms = strtoul(argv[1], NULL, 10);
  /* libnjb printf()s some errors to stdout, which would interleave with the
   * replies; keep replies on a private copy of stdout, the rest on stderr. */
  reply = fdopen(dup(STDOUT_FILENO), "w");
  dup2(STDERR_FILENO, STDOUT_FILENO);

  if (NJB_Discover(njbs, 0, &n) == -1 || n == 0) {
    fprintf(stderr, "no jukebox found\n");
    return 1;
  }
  njb = &njbs[0];
  if (NJB_Open(njb) == -1) {
    NJB_Error_Dump(njb, stderr);
    return 1;
  }
  /* Turbo mode (on by default) requests 16 KiB blocks; libnjb notes some
   * devices transfer badly with it, so use the conservative 8 KiB blocks. */
  NJB_Set_Turbo_Mode(njb, NJB_TURBO_OFF);
  if (NJB_Capture(njb) == -1) {
    NJB_Error_Dump(njb, stderr);
    NJB_Close(njb);
    return 1;
  }
  log_battery(njb);
  fprintf(reply, "READY\n");
  fflush(reply);

  while (fgets(line, sizeof line, stdin)) {
    char *id_s = strtok(line, "\t");
    char *size_s = strtok(NULL, "\t");
    char *path = strtok(NULL, "\n");
    u_int32_t id, size;

    if (!id_s || !size_s || !path)
      continue;
    id = strtoul(id_s, NULL, 10);
    size = strtoul(size_s, NULL, 10);
    if (NJB_Get_Track(njb, id, size, path, pace, NULL) == -1) {
      NJB_Error_Dump(njb, stderr);
      fprintf(reply, "ERR %u\n", id);
      fflush(reply);
    } else {
      fprintf(reply, "OK %u\n", id);
      fflush(reply);
      log_battery(njb);
    }
  }

  NJB_Release(njb);
  NJB_Close(njb);
  return 0;
}
