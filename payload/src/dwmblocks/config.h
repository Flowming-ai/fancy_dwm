/* Ubuntu desktop modules. Signals are SIGRTMIN + the last column. */
static const Block blocks[] = {
    /* Icon  Command                Seconds  Signal */
    { " ", "luke-status cpu",      10,      1 },
    { " ", "luke-status memory",   10,      2 },
    { " ", "luke-status volume",    5,      3 },
    { " ", "luke-status network",  10,      4 },
    { " ", "luke-status input",     1,      5 },
    { " ", "luke-status clock",    30,      6 },
    { " ", "luke-status help",      0,      7 },
};
static char *delim = "  ";
