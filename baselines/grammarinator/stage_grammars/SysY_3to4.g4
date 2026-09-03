grammar SysY_3to4;

// Assignment 3: a deliberately compact semantic baseline. Each erroneous
// alternative introduces one b-h/l/m error in one or two representative forms.
compUnit
    : validProgram EOF
    | leadingLines? duplicateNameProgram EOF
    | leadingLines? undefinedNameProgram EOF
    | leadingLines? argumentCountProgram EOF
    | leadingLines? argumentTypeProgram EOF
    | leadingLines? voidReturnProgram EOF
    | leadingLines? missingReturnProgram EOF
    | leadingLines? assignConstProgram EOF
    | leadingLines? printfMismatchProgram EOF
    | leadingLines? loopControlProgram EOF
    ;

validProgram
    : validScalarProgram
    | validArrayProgram
    ;

validScalarProgram
    : INT CALC '(' INT X ',' INT Y ')' '{' RETURN safeExprXY ';' '}'
      INT MAIN '(' ')' '{'
        CONST INT C '=' nonZero ';'
        INT X '=' number ',' Y '=' nonZero ';'
        X '=' CALC '(' X ',' Y ')' ';'
        IF '(' X relation Y ')' PRINTF '(' formatOne ',' X ')' ';'
        RETURN ZERO ';'
      '}'
    ;

validArrayProgram
    : INT SUM '(' INT A '[' ']' ',' INT N ')' '{'
        INT I '=' ZERO ',' S '=' ZERO ';'
        FOR '(' I '=' ZERO ';' I '<' N ';' I '=' I '+' ONE ')' S '=' S '+' A '[' I ']' ';'
        RETURN S ';'
      '}'
      INT MAIN '(' ')' '{'
        CONST INT N '=' FOUR ';'
        INT A '[' FOUR ']' '=' '{' number ',' number ',' number ',' number '}' ';'
        PRINTF '(' formatOne ',' SUM '(' A ',' N ')' ')' ';'
        RETURN ZERO ';'
      '}'
    ;

duplicateNameProgram
    : INT MAIN '(' ')' '{' INT X '=' number ';' INT X '=' nonZero ';' RETURN ZERO ';' '}'
    | INT CALC '(' INT X ',' INT X ')' '{' RETURN X ';' '}'
      INT MAIN '(' ')' '{' RETURN ZERO ';' '}'
    ;

undefinedNameProgram
    : INT MAIN '(' ')' '{' INT X '=' number ';' UNKNOWN '=' X '+' nonZero ';' RETURN ZERO ';' '}'
    | INT MAIN '(' ')' '{' INT X '=' UNKNOWN '(' number ')' ';' RETURN ZERO ';' '}'
    ;

argumentCountProgram
    : INT CALC '(' INT X ',' INT Y ')' '{' RETURN X '+' Y ';' '}'
      INT MAIN '(' ')' '{' INT Z '=' CALC '(' number ')' ';' RETURN ZERO ';' '}'
    | INT CALC '(' INT X ')' '{' RETURN X ';' '}'
      INT MAIN '(' ')' '{' INT Z '=' CALC '(' number ',' nonZero ')' ';' RETURN ZERO ';' '}'
    ;

argumentTypeProgram
    : INT FIRST '(' INT A '[' ']' ')' '{' RETURN A '[' ZERO ']' ';' '}'
      INT MAIN '(' ')' '{' INT X '=' number ';' X '=' FIRST '(' X ')' ';' RETURN ZERO ';' '}'
    | INT INC '(' INT X ')' '{' RETURN X '+' ONE ';' '}'
      INT MAIN '(' ')' '{'
        INT A '[' FOUR ']' '=' '{' number ',' number ',' number ',' number '}' ';'
        RETURN INC '(' A ')' ';'
      '}'
    ;

voidReturnProgram
    : VOID SHOW '(' INT X ')' '{' RETURN nonZero ';' '}'
      INT MAIN '(' ')' '{' SHOW '(' number ')' ';' RETURN ZERO ';' '}'
    ;

missingReturnProgram
    : INT CALC '(' ')' '{' INT X '=' number ';' '}'
      INT MAIN '(' ')' '{' RETURN ZERO ';' '}'
    | INT CALC '(' INT X ')' '{' X '=' X '+' ONE ';' '}'
      INT MAIN '(' ')' '{' RETURN ZERO ';' '}'
    ;

assignConstProgram
    : INT MAIN '(' ')' '{' CONST INT C '=' number ';' C '=' nonZero ';' RETURN ZERO ';' '}'
    | INT MAIN '(' ')' '{'
        CONST INT A '[' FOUR ']' '=' '{' number ',' number ',' number ',' number '}' ';'
        A '[' index ']' '=' nonZero ';'
        RETURN ZERO ';'
      '}'
    ;

printfMismatchProgram
    : INT MAIN '(' ')' '{' INT X '=' number ';' PRINTF '(' formatTwo ',' X ')' ';' RETURN ZERO ';' '}'
    | INT MAIN '(' ')' '{'
        INT X '=' number ',' Y '=' nonZero ';'
        PRINTF '(' formatOne ',' X ',' Y ')' ';'
        RETURN ZERO ';'
      '}'
    ;

loopControlProgram
    : INT MAIN '(' ')' '{' INT X '=' number ';' loopControl ';' RETURN ZERO ';' '}'
    ;

loopControl
    : BREAK
    | CONTINUE
    ;

safeExprXY
    : X
    | Y
    | X addOp Y
    | X '*' Y
    | X '/' nonZero
    | X '%' nonZero
    ;

relation
    : '<'
    | '>'
    | '<='
    | '>='
    | '=='
    | '!='
    ;

addOp
    : '+'
    | '-'
    ;

index
    : ZERO
    | ONE
    | TWO
    | THREE
    ;

formatOne
    : FORMAT_ONE
    ;

formatTwo
    : FORMAT_TWO
    ;

number
    : ZERO
    | ONE
    | TWO
    | THREE
    | FOUR
    | nonZero
    ;

nonZero
    : POSITIVE
    ;

leadingLines
    : NL
    | NL NL
    | NL NL NL
    ;

CONST: 'const ';
INT: 'int ';
VOID: 'void ';
MAIN: 'main';
IF: 'if';
FOR: 'for';
BREAK: 'break';
CONTINUE: 'continue';
RETURN: 'return ';
PRINTF: 'printf';
SUM: 'sum';
CALC: 'calc';
SHOW: 'show';
FIRST: 'first';
INC: 'inc';
A: 'a';
N: 'n';
I: 'i';
S: 's';
X: 'x';
Y: 'y';
Z: 'z';
C: 'c';
UNKNOWN: 'unknown';
ZERO: '0';
ONE: '1';
TWO: '2';
THREE: '3';
FOUR: '4';
FORMAT_ONE: '"%d"' | '"%d\\n"' | '"value=%d\\n"';
FORMAT_TWO: '"%d %d\\n"' | '"pair=%d,%d\\n"';
POSITIVE: [5-9] | [1-9] [0-9] | [1-9] [0-9] [0-9];
NL: '\n';
WS: [ \t\r]+ -> skip;
