#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#define STACK_SIZE 16


int 
main(int argc, char *argv[])
{	
	/* YIKES */
	char buffer[STACK_SIZE];
	printf("Writing to buffer!\n");
	
	strcpy(buffer, argv[1]);

	printf("%s\n", buffer);

	exit(EXIT_SUCCESS); // unreachable if overflowed
}
