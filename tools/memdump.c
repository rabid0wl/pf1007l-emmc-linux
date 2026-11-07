/*
 * memdump: write a physical memory range to stdout via mmap(/dev/mem). Freestanding (raw ARM EABI
 * syscalls, no libc) because the cross compiler has no C library. Used to read U-Boot's recorded
 * console from RAM above mem=, where read() on /dev/mem returns EFAULT.
 * usage: memdump <phys_hex> <len_hex>
 */
#define SYS_exit 1
#define SYS_write 4
#define SYS_open 5
#define SYS_mmap2 192

static long sc(long n, long a, long b, long c, long d, long e, long f)
{
	register long r7 asm("r7") = n;
	register long r0 asm("r0") = a, r1 asm("r1") = b, r2 asm("r2") = c;
	register long r3 asm("r3") = d, r4 asm("r4") = e, r5 asm("r5") = f;
	asm volatile("svc #0" : "+r"(r0) : "r"(r7), "r"(r1), "r"(r2), "r"(r3), "r"(r4), "r"(r5) : "memory");
	return r0;
}

static unsigned long hex(const char *s)
{
	unsigned long v = 0;
	if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X'))
		s += 2;
	for (; *s; s++)
		v = v * 16 + (*s <= '9' ? *s - '0' : (*s | 0x20) - 'a' + 10);
	return v;
}

static void die(const char *m, int len)
{
	sc(SYS_write, 2, (long)m, len, 0, 0, 0);
	sc(SYS_exit, 1, 0, 0, 0, 0, 0);
}

void cmain(long *sp)
{
	long argc = sp[0];
	char **argv = (char **)(sp + 1);
	if (argc != 3)
		die("usage: memdump <phys_hex> <len_hex>\n", 37);
	unsigned long phys = hex(argv[1]), len = hex(argv[2]);
	long fd = sc(SYS_open, (long)"/dev/mem", 0 /* O_RDONLY */, 0, 0, 0, 0);
	if (fd < 0)
		die("open /dev/mem failed\n", 21);
	/* mmap2 takes the offset in 4KiB pages; PROT_READ=1, MAP_SHARED=1 */
	long p = sc(SYS_mmap2, 0, len, 1, 1, fd, phys >> 12);
	if (p < 0 && p > -4096)
		die("mmap failed\n", 12);
	/* copy through an aligned stack buffer: the mapping is device memory, keep accesses word-sized */
	static unsigned int buf[1024];
	for (unsigned long off = 0; off < len; off += sizeof(buf)) {
		volatile unsigned int *src = (volatile unsigned int *)(p + off);
		for (int i = 0; i < 1024; i++)
			buf[i] = src[i];
		sc(SYS_write, 1, (long)buf, sizeof(buf), 0, 0, 0);
	}
	sc(SYS_exit, 0, 0, 0, 0, 0, 0);
}

asm(".global _start\n_start:\n\tmov r0, sp\n\tbl cmain\n");
