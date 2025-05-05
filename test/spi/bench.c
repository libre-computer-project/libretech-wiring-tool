#include <stdio.h>
#include <stdlib.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <linux/spi/spidev.h>
#include <string.h>
#include <time.h>
#include <stdint.h>

#define DEFAULT_SPI_DEVICE "/dev/spidev0.0"	// Default SPI device
#define DEFAULT_SPI_SPEED 10000000		// Default 10 MHz
#define DEFAULT_BITS_PER_WORD 8			// Default 8 bits
#define DEFAULT_MODE 0				// Default SPI Mode 0
#define DEFAULT_TOTAL_SIZE (1024 * 1024)	// Default 1 MB
#define DEFAULT_CHUNK_SIZE 1024			// Default 1 KB
#define MAX_MISMATCHES_TO_PRINT 16		// Limit number of mismatches printed

int main(int argc, char *argv[]) {
	int fd, ret;
	const char *device = DEFAULT_SPI_DEVICE;
	uint32_t speed = DEFAULT_SPI_SPEED;
	uint8_t bits = DEFAULT_BITS_PER_WORD;
	uint8_t mode = DEFAULT_MODE;
	uint32_t total_size = DEFAULT_TOTAL_SIZE;
	uint32_t chunk_size = DEFAULT_CHUNK_SIZE;

	// Parse command-line arguments
	if (argc > 1) {
		device = argv[1];
		if (strlen(device) == 0) {
			fprintf(stderr, "Invalid SPI device: empty string. Using default %s\n", DEFAULT_SPI_DEVICE);
			device = DEFAULT_SPI_DEVICE;
		}
	}
	if (argc > 2) {
		char *endptr;
		speed = strtoul(argv[2], &endptr, 10);
		if (*endptr != '\0' || speed == 0) {
			fprintf(stderr, "Invalid SPI speed: %s. Using default %u Hz\n", argv[2], DEFAULT_SPI_SPEED);
			speed = DEFAULT_SPI_SPEED;
		}
	}
	if (argc > 3) {
		char *endptr;
		bits = strtoul(argv[3], &endptr, 10);
		if (*endptr != '\0' || bits < 1 || bits > 64) {
			fprintf(stderr, "Invalid bits per word: %s. Using default %u\n", argv[3], DEFAULT_BITS_PER_WORD);
			bits = DEFAULT_BITS_PER_WORD;
		}
	}
	if (argc > 4) {
		char *endptr;
		mode = strtoul(argv[4], &endptr, 10);
		if (*endptr != '\0' || mode > 3) {
			fprintf(stderr, "Invalid SPI mode: %s. Using default %u\n", argv[4], DEFAULT_MODE);
			mode = DEFAULT_MODE;
		}
	}
	if (argc > 5) {
		char *endptr;
		total_size = strtoul(argv[5], &endptr, 10);
		if (*endptr != '\0' || total_size == 0) {
			fprintf(stderr, "Invalid total size: %s. Using default %u bytes\n", argv[5], DEFAULT_TOTAL_SIZE);
			total_size = DEFAULT_TOTAL_SIZE;
		}
	}
	if (argc > 6) {
		char *endptr;
		chunk_size = strtoul(argv[6], &endptr, 10);
		if (*endptr != '\0' || chunk_size == 0 || chunk_size > total_size) {
			fprintf(stderr, "Invalid chunk size: %s. Using default %u bytes\n", argv[6], DEFAULT_CHUNK_SIZE);
			chunk_size = DEFAULT_CHUNK_SIZE;
		}
	}

	// Allocate buffers
	uint8_t *tx_data = malloc(total_size);
	uint8_t *rx_data = malloc(total_size);
	if (!tx_data || !rx_data) {
		perror("Failed to allocate memory");
		return 1;
	}

	// Generate test data
	for (uint32_t i = 0; i < total_size; i++) {
		tx_data[i] = i % 256;
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

	printf("Transferring %u bytes to %s with speed %u Hz, %u bits per word, mode %u, chunk size %u...\n",
		   total_size, device, speed, bits, mode, chunk_size);

	struct timespec start, end;
	clock_gettime(CLOCK_MONOTONIC, &start);

	// Transfer in chunks
	for (uint32_t i = 0; i < total_size; i += chunk_size) {
		uint32_t current_chunk_size = (i + chunk_size <= total_size) ? chunk_size : (total_size - i);
		struct spi_ioc_transfer tr = {
			.tx_buf = (unsigned long)(tx_data + i),
			.rx_buf = (unsigned long)(rx_data + i),
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
	double throughput = total_size / duration / 1024 / 128;  // Mb/s

	printf("Transfer completed in %.2f seconds\n", duration);
	printf("Throughput: %.2f Mb/s\n", throughput);

	if (memcmp(tx_data, rx_data, total_size) == 0) {
		printf("Data verification passed: Received data matches sent data\n");
		ret = 0;
	} else {
		printf("Data verification failed: Received data does not match\n");
		printf("Offset	Sent	Received\n");
		uint32_t mismatch_count = 0;
		for (uint32_t i = 0; i < total_size && mismatch_count < MAX_MISMATCHES_TO_PRINT; i++) {
			if (tx_data[i] != rx_data[i]) {
				printf("0x%08X  0x%02X	0x%02X\n", i, tx_data[i], rx_data[i]);
				mismatch_count++;
			}
		}
		if (mismatch_count == MAX_MISMATCHES_TO_PRINT && total_size > MAX_MISMATCHES_TO_PRINT) {
			printf("(Stopped at %d mismatches; more may exist)\n", MAX_MISMATCHES_TO_PRINT);
		}
		ret = 1;
	}

	close(fd);
	free(tx_data);
	free(rx_data);
	return ret;
}
