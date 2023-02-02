//============================================================
// A simple profiling library for the loop profiler
// to profile cache read/write MPKI for all loops.
//
// This library can not be used in multi-threaded programs.
//
// By MaxXing.
//============================================================

#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <glib.h>
#include <inttypes.h>
#include <link.h>
#include <linux/perf_event.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>
#include <unistd.h>

//============================================================
// Performance Events Configurations
//============================================================

/// Numbers of all performance events.
#define LEN_PERF_EVENTS 3

/// Result of `perf_event_open`.
typedef struct {
  uint64_t nr;
  uint64_t values[LEN_PERF_EVENTS];
} read_format_t;

/// Performance data.
typedef struct {
  uint64_t values[LEN_PERF_EVENTS];
} perf_data_t;

/// Profiling data.
typedef struct {
  double read_mpki;
  double write_mpki;
} prof_data_t;

/// Loop data.
typedef struct {
  GArray *perf_data_stack;
  prof_data_t prof_data;
  bool has_prof_data;
} loop_data_t;

/// Performance event configurations.
static const struct {
  uint64_t type;
  uint64_t config;
} perf_configs[LEN_PERF_EVENTS] = {
    {PERF_TYPE_HARDWARE, PERF_COUNT_HW_INSTRUCTIONS},
    {PERF_TYPE_HW_CACHE, PERF_COUNT_HW_CACHE_L1D |
                             PERF_COUNT_HW_CACHE_OP_READ << 8 |
                             PERF_COUNT_HW_CACHE_RESULT_MISS << 16},
    {PERF_TYPE_HW_CACHE, PERF_COUNT_HW_CACHE_L1D |
                             PERF_COUNT_HW_CACHE_OP_WRITE << 8 |
                             PERF_COUNT_HW_CACHE_RESULT_MISS << 16},
};

/// Fills performance data by the given `read_format_t`.
static void fill_perf_data(perf_data_t *data, const read_format_t *rf) {
  for (int i = 0; i < LEN_PERF_EVENTS; ++i) data->values[i] = rf->values[i];
}

/// Fills profiling data by the given two performance data.
static void fill_prof_data(prof_data_t *data, const perf_data_t *last,
                           const perf_data_t *cur) {
  uint64_t num_insts = cur->values[0] - last->values[0];
  uint64_t read_misses = cur->values[1] - last->values[1];
  uint64_t write_misses = cur->values[2] - last->values[2];
  data->read_mpki = read_misses / (num_insts / 1000.0);
  data->write_mpki = write_misses / (num_insts / 1000.0);
}

/// Adds the second profiling data to the first one.
static void add_prof_data(prof_data_t *lhs, const prof_data_t *rhs) {
  lhs->read_mpki = (lhs->read_mpki + rhs->read_mpki) / 2;
  lhs->write_mpki = (lhs->write_mpki + rhs->write_mpki) / 2;
}

//============================================================
// Utilities
//============================================================

/// Marks a branch is unlikely taken.
#define UNLIKELY(x) __builtin_expect(!!(x), 0)

/// Marks a branch is likely taken.
#define LIKELY(x) __builtin_expect(!!(x), 1)

/// Reports a panic and abort.
#define PANIC(fmt, ...)                       \
  do {                                        \
    fprintf(stderr, fmt "\n", ##__VA_ARGS__); \
    abort();                                  \
  } while (0)

/// Reports an error and abort.
#define PANIC_ERR(fmt, ...) PANIC(fmt ": %s.", ##__VA_ARGS__, strerror(errno))

/// Writes and asserts no error.
static void write_assert(int fd, const void *buf, size_t size) {
  if (UNLIKELY(write(fd, buf, size) != size)) {
    PANIC_ERR("Failed to write to fd %d", fd);
  }
}

/// Reads and asserts no error.
static void read_assert(int fd, void *buf, size_t size) {
  if (UNLIKELY(read(fd, buf, size) != size)) {
    PANIC_ERR("Failed to read from fd %d", fd);
  }
}

/// Returns the relocation.
static uintptr_t get_relocation() { return _r_debug.r_map->l_addr; }

//============================================================
// Constructor and Destructor
//============================================================

/// File descriptors of all performance events.
static int perf_fds[LEN_PERF_EVENTS];

/// Hash table for loop data.
static GHashTable *loop_data_table;

/// Initializes performance events.
static void init_perf_events() {
  // Open performance events.
  struct perf_event_attr pea;
  for (int i = 0; i < LEN_PERF_EVENTS; ++i) {
    memset(&pea, 0, sizeof(struct perf_event_attr));
    pea.type = perf_configs[i].type;
    pea.size = sizeof(struct perf_event_attr);
    pea.config = perf_configs[i].config;
    pea.disabled = 1;
    pea.exclude_kernel = 1;
    pea.exclude_hv = 1;
    pea.read_format = PERF_FORMAT_GROUP;
    perf_fds[i] =
        syscall(__NR_perf_event_open, &pea, 0, -1, i ? perf_fds[0] : -1, 0);
    if (perf_fds[i] == -1) {
      PANIC_ERR("Failed to open perf event (%" PRIu64 ", %" PRIu64 ")",
                perf_configs[i].type, perf_configs[i].config);
    }
  }
  // Enable performance events.
  ioctl(perf_fds[0], PERF_EVENT_IOC_RESET, PERF_IOC_FLAG_GROUP);
  ioctl(perf_fds[0], PERF_EVENT_IOC_ENABLE, PERF_IOC_FLAG_GROUP);
}

/// Frees the given loop data.
static void free_loop_data(loop_data_t *data) {
  g_array_free(data->perf_data_stack, TRUE);
  free(data);
}

/// Initializes loop data table.
static void init_loop_data_table() {
  loop_data_table = g_hash_table_new_full(g_direct_hash, g_direct_equal, NULL,
                                          (GDestroyNotify)free_loop_data);
}

/// Performs cleanup for performance events.
static void cleanup_perf_events() {
  // Disable performance events.
  ioctl(perf_fds[0], PERF_EVENT_IOC_DISABLE, PERF_IOC_FLAG_GROUP);
  // Close performance events.
  for (int i = 0; i < LEN_PERF_EVENTS; ++i) close(perf_fds[i]);
}

/// Opens the output file and initializes it.
///
/// Returns the descriptor of the opened file.
static int open_output_file() {
  // Get the name of the output file.
  const char *output_file_name = getenv("PROFILE_OUTPUT");
  char name_buf[256];
  if (!output_file_name) {
    int ret = snprintf(name_buf, sizeof(name_buf) - 1, "%s.prof",
                       program_invocation_short_name);
    if (ret < 0 || ret >= sizeof(name_buf)) PANIC("Program name is too long.");
    output_file_name = name_buf;
  }
  // Open the file.
  int fd = open(output_file_name, O_CREAT | O_TRUNC | O_WRONLY, 0644);
  if (fd == -1) PANIC_ERR("Failed to open the output file");
  // Write relocation to the file.
  uintptr_t rel = get_relocation();
  write_assert(fd, &rel, sizeof(rel));
  return fd;
}

/// Writes the given loop profiling data information to the output file.
static void write_loop_prof(void *addr, const loop_data_t *data, int *fd) {
  // Write return address.
  write_assert(*fd, &addr, sizeof(addr));
  // Write profiling data.
  write_assert(*fd, &data->prof_data, sizeof(prof_data_t));
}

/// Performs cleanup for loop data table.
static void cleanup_loop_data_table() {
  // Write the content of the hash table to the output file.
  int fd = open_output_file();
  g_hash_table_foreach(loop_data_table, (GHFunc)write_loop_prof, &fd);
  close(fd);
  // Destory the hash table.
  g_hash_table_destroy(loop_data_table);
}

/// Initializes the program.
static void __attribute__((constructor)) init_all() {
  init_perf_events();
  init_loop_data_table();
}

/// Performs cleanup for the program.
static void __attribute__((destructor)) cleanup_all() {
  cleanup_perf_events();
  cleanup_loop_data_table();
}

//============================================================
// Profiling Functions
//============================================================

/// Finds the given loop data from the hash table by the given address,
/// inserts a new entry to the hash table if not found.
///
/// Returns a pointer to the loop data.
static loop_data_t *find_or_insert_loop_data(void *addr) {
  loop_data_t *data = (loop_data_t *)g_hash_table_lookup(loop_data_table, addr);
  if (LIKELY(data)) {
    return data;
  } else {
    loop_data_t *data = malloc(sizeof(loop_data_t));
    data->perf_data_stack = g_array_new(FALSE, FALSE, sizeof(perf_data_t));
    data->has_prof_data = false;
    g_hash_table_insert(loop_data_table, addr, data);
    return data;
  }
}

/// Loop profiler enter function.
///
/// This function is marked as `noinline` because it calls
/// `__builtin_return_address`.
void *__attribute__((noinline)) __loop_profile_func_enter() {
  // Get the corresponding loop data.
  void *addr = __builtin_extract_return_addr(__builtin_return_address(0));
  loop_data_t *loop_data = find_or_insert_loop_data(addr);
  // Allocate space on stack.
  GArray *stack = loop_data->perf_data_stack;
  g_array_set_size(stack, stack->len + 1);
  perf_data_t *perf_data = (perf_data_t *)stack->data + stack->len - 1;
  // Write performance data to stack.
  read_format_t rf;
  read_assert(perf_fds[0], &rf, sizeof(rf));
  fill_perf_data(perf_data, &rf);
  return addr;
}

/// Loop profiler exit function.
void __loop_profile_func_exit(void *addr) {
  // Read performance data.
  read_format_t rf;
  read_assert(perf_fds[0], &rf, sizeof(rf));
  perf_data_t perf_data;
  fill_perf_data(&perf_data, &rf);
  // Get the corresponding loop data.
  loop_data_t *loop_data =
      (loop_data_t *)g_hash_table_lookup(loop_data_table, addr);
  if (UNLIKELY(!loop_data)) PANIC("Loop data not found!");
  // Get performance data from stack.
  GArray *stack = loop_data->perf_data_stack;
  if (UNLIKELY(!stack->len)) PANIC("Performance data stack is empty!");
  perf_data_t *prev_perf_data = (perf_data_t *)stack->data + stack->len - 1;
  // Update the profiling data.
  if (LIKELY(loop_data->has_prof_data)) {
    prof_data_t prof_data;
    fill_prof_data(&prof_data, prev_perf_data, &perf_data);
    add_prof_data(&loop_data->prof_data, &prof_data);
  } else {
    fill_prof_data(&loop_data->prof_data, prev_perf_data, &perf_data);
    loop_data->has_prof_data = true;
  }
  // Pop performance data from stack.
  g_array_set_size(stack, stack->len - 1);
}
