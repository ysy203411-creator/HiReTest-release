grammar SysY_1to2;

// Assignment 1: broad token coverage plus one controlled a-class error.
compUnit
    : validProgram EOF
    | leadingLines? illegalAndProgram EOF
    | leadingLines? illegalOrProgram EOF
    ;

validProgram
    : comprehensiveProgram
    | arithmeticProgram
    | commentProgram
    | identifierProgram
    | stringProgram
    ;

comprehensiveProgram
    : comment?
      CONST INT LIMIT '=' nonZero ';'
      INT VALUES '[' FOUR ']' '=' '{' number ',' number ',' number ',' number '}' ';'
      INT BUMP '(' INT PARAM ')' '{' RETURN PARAM '+' nonZero ';' '}'
      VOID EMIT '(' INT PARAM ')' '{' PRINTF '(' formatOne ',' PARAM ')' ';' RETURN ';' '}'
      INT MAIN '(' ')' '{'
        STATIC INT STATE '=' number ';'
        INT INDEX '=' ZERO ';'
        FOR '(' INDEX '=' ZERO ';' INDEX '<' FOUR ';' INDEX '=' INDEX '+' ONE ')' '{'
          IF '(' VALUES '[' INDEX ']' '!=' ZERO AND INDEX '>=' ZERO ')'
            '{' EMIT '(' BUMP '(' VALUES '[' INDEX ']' ')' ')' ';' '}'
          ELSE '{' CONTINUE ';' '}'
          IF '(' INDEX '==' THREE ')' '{' BREAK ';' '}'
        '}'
        IF '(' '!' STATE OR STATE '<=' LIMIT ')' STATE '=' STATE '+' ONE ';'
        RETURN ZERO ';'
      '}'
      comment?
    ;

arithmeticProgram
    : INT MAIN '(' ')' '{'
        INT VALUE '=' GETINT '(' ')' ';'
        INT OTHER '=' nonZero ';'
        VALUE '=' signedAtom arithmetic safeOperand ';'
        OTHER '=' '(' VALUE addOp nonZero ')' mulOp safeOperand ';'
        PRINTF '(' formatTwo ',' VALUE ',' OTHER ')' ';'
        RETURN ZERO ';'
      '}'
    ;

commentProgram
    : comment
      INT MAIN '(' ')' '{'
        comment?
        INT UNDERSCORE_NAME '=' longNumber ';'
        comment?
        PRINTF '(' plainString ')' ';'
        comment?
        RETURN ZERO ';'
      '}'
    ;

identifierProgram
    : INT MAIN '(' ')' '{'
        INT VALUE2025 '=' number ',' LONG_NAME '=' longNumber ';'
        LONG_NAME '=' VALUE2025 addOp nonZero ';'
        PRINTF '(' formatTwo ',' VALUE2025 ',' LONG_NAME ')' ';'
        RETURN ZERO ';'
      '}'
    ;

stringProgram
    : INT MAIN '(' ')' '{'
        INT VALUE '=' number ';'
        PRINTF '(' plainString ')' ';'
        PRINTF '(' formatOne ',' VALUE ')' ';'
        PRINTF '(' formatTwo ',' VALUE ',' VALUE ')' ';'
        RETURN ZERO ';'
      '}'
    ;

illegalAndProgram
    : INT MAIN '(' ')' '{' NL INT VALUE '=' number ';' NL badAndStmt NL RETURN ZERO ';' NL '}'
    ;

badAndStmt
    : IF '(' VALUE BAD_AND ONE ')' VALUE '=' VALUE '+' ONE ';'
    | IF '(' VALUE '<' nonZero BAD_AND VALUE '!=' ZERO ')' '{' VALUE '=' VALUE '-' ONE ';' '}'
    | IF '(' '!' VALUE BAD_AND VALUE '<=' nonZero ')' PRINTF '(' formatOne ',' VALUE ')' ';'
    ;

illegalOrProgram
    : INT MAIN '(' ')' '{' NL INT VALUE '=' number ';' NL badOrStmt NL RETURN ZERO ';' NL '}'
    ;

badOrStmt
    : IF '(' VALUE BAD_OR ZERO ')' VALUE '=' VALUE '-' ONE ';'
    | IF '(' VALUE '==' ZERO BAD_OR VALUE '>' nonZero ')' '{' VALUE '=' VALUE '+' ONE ';' '}'
    | IF '(' '!' VALUE BAD_OR VALUE '>=' ZERO ')' PRINTF '(' formatOne ',' VALUE ')' ';'
    ;

signedAtom
    : VALUE
    | '+' VALUE
    | '-' VALUE
    ;

safeOperand
    : OTHER
    | nonZero
    ;

arithmetic
    : '+'
    | '-'
    | '*'
    | '/'
    | '%'
    ;

addOp
    : '+'
    | '-'
    ;

mulOp
    : '*'
    | '/'
    | '%'
    ;

formatOne
    : FORMAT_ONE
    ;

formatTwo
    : FORMAT_TWO
    ;

plainString
    : PLAIN_STRING
    ;

comment
    : LINE_COMMENT_TEXT
    | BLOCK_COMMENT_TEXT
    ;

leadingLines
    : NL
    | NL NL
    | NL NL NL
    ;

longNumber
    : LONG_INT
    | nonZero
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

CONST: 'const ';
STATIC: 'static ';
INT: 'int ';
VOID: 'void ';
MAIN: 'main';
IF: 'if';
ELSE: 'else';
FOR: 'for';
BREAK: 'break';
CONTINUE: 'continue';
RETURN: 'return ';
PRINTF: 'printf';
GETINT: 'getint';
LIMIT: 'limit';
VALUES: 'values';
BUMP: 'bump';
EMIT: 'emit';
PARAM: 'param';
STATE: 'state';
INDEX: 'index';
VALUE: 'value';
OTHER: 'other';
UNDERSCORE_NAME: '_value';
VALUE2025: 'value2025';
LONG_NAME: 'long_identifier_name';
ZERO: '0';
ONE: '1';
TWO: '2';
THREE: '3';
FOUR: '4';
BAD_AND: '&';
BAD_OR: '|';
AND: '&&';
OR: '||';
FORMAT_ONE: '"%d"' | '"%d\\n"' | '"value=%d\\n"' | '"[%d]"';
FORMAT_TWO: '"%d %d\\n"' | '"pair=%d,%d\\n"' | '"%d:%d"';
PLAIN_STRING: '""' | '"ok"' | '"hello world\\n"' | '"symbols: +-*"';
LINE_COMMENT_TEXT: '// lexer comment\n';
BLOCK_COMMENT_TEXT: '/* block comment */';
LONG_INT: '1000' | '65535' | '2147483647';
POSITIVE: [5-9] | [1-9] [0-9] | [1-9] [0-9] [0-9];
NL: '\n';
WS: [ \t\r]+ -> skip;
