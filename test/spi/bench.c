#include <stdio.h>
#include <stdlib.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <linux/spi/spidev.h>
#include <string.h>
#include <time.h>
#include <stdint.h>
#include <inttypes.h>
#include <signal.h>
#include <sys/types.h>

#define DEFAULT_SPI_DEVICE "/dev/spidev0.0"	// Default SPI device
#define DEFAULT_SPI_SPEED 10000000		// Default 10 MHz
#define DEFAULT_BITS_PER_WORD 8			// Default 8 bits
#define DEFAULT_MODE 0				// Default SPI Mode 0
#define DEFAULT_TOTAL_SIZE (1024 * 1024)	// Default 1 MB
#define DEFAULT_CHUNK_SIZE 1024			// Default 1 KB
#define MAX_MISMATCHES_TO_PRINT 9		// Limit number of mismatches printed
#define MAX_WORDS_TO_PREVIEW 16			// Limit words to preview

// Pattern types
typedef enum {
	PATTERN_RANDOM,
	PATTERN_ONES,
	PATTERN_ZEROS,
	PATTERN_ALTERNATING,
	PATTERN_INCREMENTING,
	PATTERN_DELAY
} PatternType;

// Function to print help message and exit
void print_help(const char *prog_name) {
	printf("Usage: %s [device] [speed] [bits] [mode] [total_size] [chunk_size] [-h|--help]\n\n", prog_name);
	printf("Benchmark program for SPI device data transfer.\n\n");
	printf("Parameters:\n");
	printf("  device	SPI device path (default: %s)\n", DEFAULT_SPI_DEVICE);
	printf("  speed		SPI clock speed in Hz (default: %u)\n", DEFAULT_SPI_SPEED);
	printf("  bits		Bits per word (1 to 64) (default: %u)\n", DEFAULT_BITS_PER_WORD);
	printf("  mode		SPI mode (0-3, or with flags) (default: %u)\n", DEFAULT_MODE);
	printf("  total_size	Total data size in bytes (default: %u)\n", DEFAULT_TOTAL_SIZE);
	printf("  chunk_size	Data chunk size in bytes (default: %u)\n", DEFAULT_CHUNK_SIZE);
	printf("  -h, --help	Display this help message and exit\n");
	printf("\nEnvironment Variables:\n");
	printf("  PATTERN	Data pattern to use (default: random)\n");
	printf("		Options: random (random words), ones (all 1s), zeros (all 0s),\n");
	printf("		alternating (0x55/0xAA), incrementing (0,1,2,3), delay (alt+inc)\n");
	printf("\nExample:\n");
	printf("  %s /dev/spidev0.0 10000000 8 0 1048576 1024\n", prog_name);
	printf("	Transfers 1 MB of data to /dev/spidev0.0 at 10 MHz, 8 bits per word, mode 0, in 1 KB chunks.\n");
	printf("  PATTERN=incrementing %s /dev/spidev0.0 10000000 8 0 1048576 1024\n", prog_name);
	printf("	Same as above, but uses incrementing data pattern (0, 1, 2, ...).\n");
	exit(0);
}

// Function to print value as binary with specified bit width
void print_binary(uint64_t value, uint8_t bits) {
	int i, j;
	j = bits - 1;
	for (i = j; i >= 0; i--) {
		if ((i % 8) == 7 && i != j) putchar(' ');
		putchar(48 + ((value >> i) & 1));
	}
}

// Pack a single word into a buffer at the specified word index
void pack_word(uint8_t *buffer, uint32_t word_index, uint64_t word, uint8_t bits_per_word) {
	// Mask word to ensure it fits within bits_per_word
	uint64_t mask = (bits_per_word >= 64) ? UINT64_MAX : (1ULL << bits_per_word) - 1;
	word &= mask;

	if (bits_per_word >= 8) {
		// Byte-aligned packing: use minimum bytes needed
		uint32_t bytes_per_word = (bits_per_word + 7) / 8;
		uint32_t byte_index = word_index * bytes_per_word;
		int i;
		for (i = 0; i < bytes_per_word; i++) {
			buffer[byte_index + i] = (word >> (i * 8)) & 0xFF;
		}
	} else {
		// Sub-byte words: align to 4-bit or 8-bit boundaries
		uint8_t aligned_bits_per_word = bits_per_word;
		if (bits_per_word == 3) {
			aligned_bits_per_word = 4; // Align 3 bpw to 4 bits
		} else if (bits_per_word >= 5 && bits_per_word <= 7) {
			aligned_bits_per_word = 8; // Align 5,6,7 bpw to 8 bits
		}
		// For bpw=1,2,4, aligned_bits_per_word remains 1,2,4
		uint32_t words_per_byte = 8 / aligned_bits_per_word;
		uint32_t byte_index = word_index / words_per_byte;
		uint32_t word_offset = word_index % words_per_byte;
		// Shift word into correct position
		buffer[byte_index] |= (word << (aligned_bits_per_word * (words_per_byte - 1 - word_offset)));
	}
}

// Unpack a single word from a buffer at the specified word index
uint64_t unpack_word(const uint8_t *buffer, uint32_t word_index, uint8_t bits_per_word) {
	if (bits_per_word >= 8) {
		// Byte-aligned unpacking: use minimum bytes needed
		uint32_t bytes_per_word = (bits_per_word + 7) / 8;
		uint32_t byte_index = word_index * bytes_per_word;
		uint64_t word = 0;
		int i;
		for (i = 0; i < bytes_per_word; i++) {
			word |= ((uint64_t)buffer[byte_index + i]) << (i * 8);
		}
		// Mask to ensure only bits_per_word bits are returned
		uint64_t mask = (bits_per_word >= 64) ? UINT64_MAX : (1ULL << bits_per_word) - 1;
		return word & mask;
	} else {
		// Sub-byte words: align to 4-bit or 8-bit boundaries
		uint8_t aligned_bits_per_word = bits_per_word;
		if (bits_per_word == 3) {
			aligned_bits_per_word = 4; // Align 3 bpw to 4 bits
		} else if (bits_per_word >= 5 && bits_per_word <= 7) {
			aligned_bits_per_word = 8; // Align 5,6,7 bpw to 8 bits
		}
		// For bpw=1,2,4, aligned_bits_per_word remains 1,2,4
		uint32_t words_per_byte = 8 / aligned_bits_per_word;
		uint32_t byte_index = word_index / words_per_byte;
		uint32_t word_offset = word_index % words_per_byte;
		uint64_t mask = (1ULL << bits_per_word) - 1;
		// Extract word from correct position
		return (buffer[byte_index] >> (aligned_bits_per_word * (words_per_byte - 1 - word_offset))) & mask;
	}
}

int main(int argc, char *argv[]) {
	int fd, ret;
	const char *device = DEFAULT_SPI_DEVICE;
	uint32_t speed = DEFAULT_SPI_SPEED;
	uint8_t bits = DEFAULT_BITS_PER_WORD;
	uint8_t mode = DEFAULT_MODE;
	uint32_t total_size = DEFAULT_TOTAL_SIZE;
	uint32_t chunk_size = DEFAULT_CHUNK_SIZE;
	char *parent_usr1 = getenv("PARENT_USR1");

	// Check for -h or --help
	int i, j;
	for (i = 1; i < argc; i++) {
		if (strcmp(argv[i], "-h") == 0 || strcmp(argv[i], "--help") == 0) {
			print_help(argv[0]);
		}
	}

	// Parse command-line arguments
	if (argc > 1) {
		device = argv[1];
		if (strlen(device) == 0) {
			fprintf(stderr, "Invalid SPI device: empty string.\n");
			return 1;
		}
	}
	if (argc > 2) {
		char *endptr;
		speed = strtoul(argv[2], &endptr, 10);
		if (*endptr != '\0' || speed == 0) {
			fprintf(stderr, "Invalid SPI speed: %s.\n", argv[2]);
			return 1;
		}
	}
	if (argc > 3) {
		char *endptr;
		bits = strtoul(argv[3], &endptr, 10);
		if (*endptr != '\0' || bits < 1 || bits > 64) {
			fprintf(stderr, "Invalid bits per word: %s. Must be 1 to 64.\n", argv[3]);
			return 1;
		}
	}
	if (argc > 4) {
		char *endptr;
		mode = strtoul(argv[4], &endptr, 10);
		if (*endptr != '\0' || (mode & ~(1<<5)) > 3) {
			fprintf(stderr, "Invalid SPI mode: %s.\n", argv[4]);
			return 1;
		}
	}
	if (argc > 5) {
		char *endptr;
		total_size = strtoul(argv[5], &endptr, 10);
		if (*endptr != '\0' || total_size == 0) {
			fprintf(stderr, "Invalid total size: %s.\n", argv[5]);
			return 1;
		}
	}
	if (argc > 6) {
		char *endptr;
		chunk_size = strtoul(argv[6], &endptr, 10);
		if (*endptr != '\0' || chunk_size == 0) {
			fprintf(stderr, "Invalid chunk size: %s.\n", argv[6]);
			return 1;
		}
	}

	// Ensure chunk_size does not exceed total_size
	if (chunk_size > total_size) {
		chunk_size = total_size;
	}

	// Calculate total words and bytes per word
	uint32_t total_words;
	uint32_t bytes_per_word;
	if (bits >= 8) {
		// Byte-aligned packing: use minimum bytes needed
		bytes_per_word = (bits + 7) / 8;
		// Calculate total_words based on total_size
		total_words = total_size / bytes_per_word;
		if (total_size % bytes_per_word != 0) {
			fprintf(stderr, "Total size %u is not a multiple of bytes per word %u\n",
				total_size, bytes_per_word);
			return 1;
		}
	} else {
		// Sub-byte words: align to 4-bit or 8-bit boundaries
		uint8_t aligned_bits_per_word = bits;
		if (bits == 3) {
			aligned_bits_per_word = 4; // Align 3 bpw to 4 bits
		} else if (bits >= 5 && bits <= 7) {
			aligned_bits_per_word = 8; // Align 5,6,7 bpw to 8 bits
		}
		// For bpw=1,2,4, aligned_bits_per_word remains 1,2,4
		uint32_t words_per_byte = 8 / aligned_bits_per_word;
		total_words = total_size * words_per_byte;
		if (total_words < words_per_byte) {
			total_words = words_per_byte;
			total_size = 1; // Minimum 1 byte
		}
		bytes_per_word = 1; // For sub-byte, still 1 byte per byte
	}

	// Allocate buffers
	uint8_t *tx_data = calloc(total_size, 1);
	uint8_t *rx_data = calloc(total_size, 1);
	if (!tx_data || !rx_data) {
		perror("Failed to allocate memory");
		return 1;
	}

	// Determine pattern from environment variable
	PatternType pattern = PATTERN_RANDOM;
	char *pattern_env = getenv("PATTERN");
	if (pattern_env) {
		if (strcmp(pattern_env, "random") == 0) {
			pattern = PATTERN_RANDOM;
		} else if (strcmp(pattern_env, "ones") == 0) {
			pattern = PATTERN_ONES;
		} else if (strcmp(pattern_env, "zeros") == 0) {
			pattern = PATTERN_ZEROS;
		} else if (strcmp(pattern_env, "alternating") == 0) {
			pattern = PATTERN_ALTERNATING;
		} else if (strcmp(pattern_env, "incrementing") == 0) {
			pattern = PATTERN_INCREMENTING;
		} else if (strcmp(pattern_env, "delay") == 0) {
			pattern = PATTERN_DELAY;
		} else 
			fprintf(stderr, "Warning: Unknown PATTERN '%s'. Using random pattern.\n", pattern_env);
	}

	// Generate test data
	uint64_t max_value = (bits >= 64) ? UINT64_MAX : (1ULL << bits) - 1;
	uint64_t word;
	srand(time(NULL));
	int r = (pattern == PATTERN_DELAY) ? rand() % 4 : 0; // Random offset only for default
	for (i = 0; i < total_words; i++) {
		switch (pattern) {
			case PATTERN_DELAY:
				j = i + r;
				if (j % 4 == 0)
					pack_word(tx_data, i, 0x5555555555555555 & max_value, bits);
				else if (j % 4 == 2)
					pack_word(tx_data, i, 0xAAAAAAAAAAAAAAAA & max_value, bits);
				else {
					word = ((i >> 1) % (max_value + 1));
					pack_word(tx_data, i, word, bits);
				}
				break;
			case PATTERN_RANDOM:
				word = ((uint64_t)rand() * rand()) % (max_value + 1);
				pack_word(tx_data, i, word, bits);
				break;
			case PATTERN_ONES:
				pack_word(tx_data, i, max_value, bits);
				break;
			case PATTERN_ZEROS:
				pack_word(tx_data, i, 0, bits);
				break;
			case PATTERN_ALTERNATING:
				pack_word(tx_data, i, (i % 2 == 0) ? (0x5555555555555555 & max_value) : (0xAAAAAAAAAAAAAAAA & max_value), bits);
				break;
			case PATTERN_INCREMENTING:
				word = i; // Simple incrementing sequence
				pack_word(tx_data, i, word, bits);
				break;
		}
	}

	// Open SPI device
	fd = open(device, O_RDWR);
	if (fd < 0) {
		fprintf(stderr, "Failed to open SPI device: %s\n", device);
		perror("Error");
		free(tx_data);
		free(rx_data);
		return 1;
	}

	// Configure SPI
	if (ioctl(fd, SPI_IOC_WR_MODE, &mode) < 0 ||
		ioctl(fd, SPI_IOC_WR_BITS_PER_WORD, &bits) < 0 ||
		ioctl(fd, SPI_IOC_WR_MAX_SPEED_HZ, &speed) < 0) {
		perror("Failed to configure SPI");
		close(fd);
		free(tx_data);
		free(rx_data);
		return 1;
	}

	printf("Transferring %u bytes (%u words) to %s with speed %u Hz, %u bits per word, mode %u, chunk size %u...\n",
		total_size, total_words, device, speed, bits, mode, chunk_size);

	struct timespec start, end;
	clock_gettime(CLOCK_MONOTONIC, &start);

	if (parent_usr1 != NULL && strcmp(parent_usr1, "1") == 0) {
		pid_t ppid = getppid();
		if (ppid != 1) kill(getppid(), SIGUSR1);
	}

	// Transfer in chunks
	for (i = 0; i < total_size; i += chunk_size) {
		uint32_t current_chunk_size = (i + chunk_size <= total_size) ? chunk_size : (total_size - i);
		struct spi_ioc_transfer tr = {
			.tx_buf = (uintptr_t)(tx_data + i),
			.rx_buf = (uintptr_t)(rx_data + i),
			.len = current_chunk_size,
			.speed_hz = speed,
			.bits_per_word = bits,
		};

		if (ioctl(fd, SPI_IOC_MESSAGE(1), &tr) < 0) {
			perror("Failed to perform SPI transfer");
			close(fd);
			free(tx_data);
			free(rx_data);
			return 1;
		}
	}

	clock_gettime(CLOCK_MONOTONIC, &end);
	double duration = (end.tv_sec - start.tv_sec) + (end.tv_nsec - start.tv_nsec) / 1e9;
	double throughput = total_size / duration / 1024 / 128; // Mb/s

	printf("Transfer completed in %.2f seconds\n", duration);
	printf("Throughput: %.2f Mb/s\n", throughput);

	// Verify data
	uint32_t mismatch_count = 0;
	for (i = 0; i < total_words; i++) {
		// For the last word, check if it's partial
		uint64_t tx_word = unpack_word(tx_data, i, bits);
		uint64_t rx_word = unpack_word(rx_data, i, bits);
		if (i == total_words - 1) {
			// Calculate total bits used
			uint64_t total_bits_used = (uint64_t)total_size * 8;
			uint32_t bits_in_last_word = total_bits_used % bits;
			if (bits_in_last_word == 0) {
				bits_in_last_word = bits;
			}
			// Mask to only the used bits in the last word
			uint64_t mask = (1ULL << bits_in_last_word) - 1;
			tx_word &= mask;
			rx_word &= mask;
		}
		if (tx_word != rx_word) {
			if (mismatch_count < MAX_MISMATCHES_TO_PRINT) {
				if (bits < 8) {
					// Sub-byte BPW: print decimal and binary
					printf("Word %u: Sent %" PRIu64 " (", i, tx_word);
					print_binary(tx_word, bits);
					printf(") Received %" PRIu64 " (", rx_word);
					print_binary(rx_word, bits);
					printf(")\n");
				} else {
					// Byte/multi-byte BPW: print decimal, hex, and binary
					printf("Word %u: Sent 0x%0*" PRIX64 " (", i, (bits + 3) / 4, tx_word);
					print_binary(tx_word, bits);
					printf(") Received 0x%0*" PRIX64 " (", (bits + 3) / 4, rx_word);
					print_binary(rx_word, bits);
					printf(")\n");
				}
			}
			mismatch_count++;
		}
	}
	if (mismatch_count == 0) {
		printf("Data verification passed: Received data matches sent data\n");
		ret = 0;
	} else {
		printf("Data verification failed: %u mismatches / %u words (%d%%).\n", mismatch_count, total_words, 100 * mismatch_count / total_words);
		ret = 1;
	}

	close(fd);
	free(tx_data);
	free(rx_data);
	return ret;
}
