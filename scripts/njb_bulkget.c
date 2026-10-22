/*
 * Copy many tracks off a Creative jukebox in ONE libnjb session.
 *
 * Opening and capturing the device once per track (as the gettr sample
 * does) makes the Zen Micro dock/undock for every file, which eventually
 * hangs its firmware. This keeps the device captured for the whole run.
 *
 * Usage: njb_bulkget [pause in ms per MiB [bytes per chunk request]]
 *
 * stdin:  one request per line: "<trackid>\t<size>\t<output path>", plus
 *         "\t<offset>" to write only the bytes from that offset to the end,
 *         and "\t<end>" to stop at that offset instead
 * stdout: "READY" once captured, then "OK <id>" or "ERR <id>" per request.
 *         libnjb's own diagnostics and battery changes go to stderr.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include "libnjb.h"

#define CHUNK_SIZE 0x100000U /* libnjb asks the player for 1 MiB at a time */
#define BLOCK_SIZE 0x2000U   /* and reads it in 8 KiB blocks with turbo off */

/* libnjb internals (protocol3.h, not installed): request the chunk of a file
 * that starts at a given offset, then read it block by block. The chunk
 * size comes from src/libnjb-request-size.patch. */
int njb3_request_file_chunk(njb_t *njb, u_int32_t fileid, u_int32_t offset);
int njb3_get_file_block(njb_t *njb, unsigned char *data, u_int32_t maxsize);
extern u_int32_t njb3_request_size;

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

/* NJB_Get_Track always starts at byte 0; this starts at `offset`, to read
 * past a spot that hangs the player. Writes bytes offset..end-1 of the track
 * to `path` as they arrive, following libnjb's own read loop. Stopping before
 * the end of the track lets a read avoid a spot known to hang the player;
 * the last chunk may then go a little past `end`. */
static int get_from(njb_t *njb, u_int32_t id, u_int32_t size,
                    u_int32_t offset, u_int32_t end, const char *path)
{
  unsigned char block[BLOCK_SIZE];
  int fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
  u_int32_t mib = offset / CHUNK_SIZE;
  int ret = -1;

  if (fd == -1) {
    perror(path);
    return -1;
  }
  while (offset < end) {
    int left = njb3_request_file_chunk(njb, id, offset);

    if (left <= 0) /* error, or the player says the file ends here */
      goto out;
    /* every block of a requested chunk must be read before the next request */
    while (left > 0) {
      int n = njb3_get_file_block(njb, block, BLOCK_SIZE);

      if (n <= 0)
        goto out;
      if (n > left) /* the player sometimes sends one extra byte */
        n = left;
      if (write(fd, block, n) != n) {
        perror(path);
        goto out;
      }
      left -= n;
      offset += n;
    }
    /* between requests, the same rest per MiB as pace() */
    if (chunk_pause_ms && offset < end && offset / CHUNK_SIZE != mib) {
      usleep(chunk_pause_ms * 1000);
      mib = offset / CHUNK_SIZE;
    }
  }
  /* libnjb ends every transfer by asking for the chunk at the end of the
   * file, which the player answers with an empty one */
  ret = end < size || njb3_request_file_chunk(njb, id, offset) == 0 ? 0 : -1;
out:
  close(fd);
  return ret;
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
  if (argc > 2)
    njb3_request_size = strtoul(argv[2], NULL, 10);
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
    char *path = strtok(NULL, "\t\n");
    char *offset_s = strtok(NULL, "\t\n");
    char *end_s = strtok(NULL, "\n");
    u_int32_t id, size, offset, end;
    int ret;

    if (!id_s || !size_s || !path)
      continue;
    id = strtoul(id_s, NULL, 10);
    size = strtoul(size_s, NULL, 10);
    offset = offset_s ? strtoul(offset_s, NULL, 10) : 0;
    end = end_s ? strtoul(end_s, NULL, 10) : size;
    if (end > size)
      end = size;
    if (offset || end < size)
      ret = get_from(njb, id, size, offset, end, path);
    else
      ret = NJB_Get_Track(njb, id, size, path, pace, NULL);
    if (ret == -1) {
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
