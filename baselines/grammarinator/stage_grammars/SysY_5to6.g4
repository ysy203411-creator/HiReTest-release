grammar SysY_5to6;

// Assignment 5: correct full-language programs built from safe compositional fragments.
compUnit
    : scalarControlProgram EOF
    | arrayFunctionProgram EOF
    | shortCircuitProgram EOF
    | staticProgram EOF
    | recursionProgram EOF
    | inputProgram EOF
    | mixedProgram EOF
    ;

scalarControlProgram
    : scalarGlobals?
      INT MAIN '(' ')' '{'
        scalarDecl
        scalarStmt
        controlStmt
        scalarStmt?
        scalarOutput
        RETURN ZERO ';'
      '}'
    ;

scalarGlobals
    : CONST INT C '=' nonZero ';'
    | INT G '=' number ';'
    | CONST INT C '=' nonZero ';' INT G '=' number ';'
    ;

arrayFunctionProgram
    : sumFunction transformFunction
      INT MAIN '(' ')' '{'
        INT A '[' FOUR ']' '=' '{' number ',' number ',' number ',' number '}' ';'
        INT X '=' number ',' Y '=' nonZero ';'
        arrayStmt arrayStmt?
        X '=' SUM '(' A ',' FOUR ')' ';'
        Y '=' TRANSFORM '(' X ',' Y ')' ';'
        arrayOutput
        RETURN ZERO ';'
      '}'
    ;

sumFunction
    : INT SUM '(' INT A '[' ']' ',' INT N ')' '{'
        INT I '=' ZERO ',' TOTAL '=' ZERO ';'
        FOR '(' I '=' ZERO ';' I '<' N ';' I '=' I '+' ONE ')' TOTAL '=' TOTAL '+' A '[' I ']' ';'
        RETURN TOTAL ';'
      '}'
    ;

transformFunction
    : INT TRANSFORM '(' INT P ',' INT Q ')' '{'
        INT R '=' safeExprPQ ';'
        IF '(' R '<' ZERO ')' R '=' '-' R ';'
        RETURN R ';'
      '}'
    ;

shortCircuitProgram
    : sideFunction
      INT MAIN '(' ')' '{'
        INT X '=' zeroOrPositive ',' Y '=' nonZero ';'
        shortCircuitStmt shortCircuitStmt?
        PRINTF '(' formatTwo ',' X ',' Y ')' ';'
        RETURN ZERO ';'
      '}'
    ;

sideFunction
    : INT SIDE '(' INT P ')' '{' PRINTF '(' formatOne ',' P ')' ';' RETURN ONE ';' '}'
    ;

shortCircuitStmt
    : IF '(' X '!=' ZERO AND Y '/' X '>' ONE ')' X '=' X '+' ONE ';'
    | IF '(' X '==' ZERO OR SIDE '(' X ')' ')' Y '=' Y '+' ONE ';'
    | IF '(' X '>' ZERO AND Y '>' ZERO OR SIDE '(' Y ')' ')' '{' X '=' X '+' Y ';' '}'
    | IF '(' '!' X OR '(' Y '>' X AND X '!=' ZERO ')' ')' PRINTF '(' formatOne ',' Y ')' ';'
    ;

staticProgram
    : nextFunction
      INT MAIN '(' ')' '{'
        INT X '=' NEXT '(' ')' ',' Y '=' NEXT '(' ')' ';'
        staticCall staticCall?
        PRINTF '(' formatTwo ',' X ',' Y ')' ';'
        RETURN ZERO ';'
      '}'
    ;

nextFunction
    : INT NEXT '(' ')' '{'
        STATIC INT STATE '=' number ';'
        STATE '=' STATE addOp nonZero ';'
        RETURN STATE ';'
      '}'
    ;

staticCall
    : X '=' NEXT '(' ')' ';'
    | Y '=' NEXT '(' ')' ';'
    | X '=' X addOp NEXT '(' ')' ';'
    ;

recursionProgram
    : fibFunction INT MAIN '(' ')' '{' INT X '=' FIB '(' smallBound ')' ';' PRINTF '(' formatOne ',' X ')' ';' RETURN ZERO ';' '}'
    | factFunction INT MAIN '(' ')' '{' INT X '=' FACT '(' smallBound ')' ';' PRINTF '(' formatOne ',' X ')' ';' RETURN ZERO ';' '}'
    | countdownFunction INT MAIN '(' ')' '{' INT X '=' COUNTDOWN '(' smallBound ')' ';' PRINTF '(' formatOne ',' X ')' ';' RETURN ZERO ';' '}'
    ;

fibFunction
    : INT FIB '(' INT N ')' '{'
        IF '(' N '<=' ONE ')' RETURN N ';'
        RETURN FIB '(' N '-' ONE ')' '+' FIB '(' N '-' TWO ')' ';'
      '}'
    ;

factFunction
    : INT FACT '(' INT N ')' '{'
        IF '(' N '<=' ONE ')' RETURN ONE ';'
        RETURN N '*' FACT '(' N '-' ONE ')' ';'
      '}'
    ;

countdownFunction
    : INT COUNTDOWN '(' INT N ')' '{'
        IF '(' N '==' ZERO ')' RETURN ZERO ';'
        RETURN ONE '+' COUNTDOWN '(' N '-' ONE ')' ';'
      '}'
    ;

inputProgram
    : inputHelper
      INT MAIN '(' ')' '{'
        inputDecl
        INT I '=' ZERO ';'
        inputStmt inputStmt?
        inputOutput
        RETURN ZERO ';'
      '}'
    ;

inputHelper
    : INT COMBINE '(' INT P ',' INT Q ')' '{' RETURN safeExprPQ ';' '}'
    ;

inputDecl
    : INT X '=' GETINT '(' ')' ';' INT Y '=' number ';'
    | INT X '=' GETINT '(' ')' ',' Y '=' GETINT '(' ')' ';'
    | INT X ';' X '=' GETINT '(' ')' ';' INT Y '=' nonZero ';'
    ;

inputStmt
    : X '=' COMBINE '(' X ',' Y ')' ';'
    | Y '=' COMBINE '(' Y ',' nonZero ')' ';'
    | IF '(' X relation Y ')' X '=' X addOp nonZero ';'
    | FOR '(' I '=' ZERO ';' I '<' smallBound ';' I '=' I '+' ONE ')' X '=' X '+' I ';'
    ;

inputOutput
    : PRINTF '(' formatOne ',' X ')' ';'
    | PRINTF '(' formatTwo ',' X ',' Y ')' ';'
    | PRINTF '(' formatOne ',' COMBINE '(' X ',' Y ')' ')' ';'
    ;

mixedProgram
    : mixedGlobals sumFunction transformFunction
      INT MAIN '(' ')' '{'
        INT A '[' FOUR ']' '=' '{' number ',' number ',' number ',' number '}' ';'
        INT X '=' GETINT '(' ')' ',' Y '=' nonZero ',' I '=' ZERO ';'
        FOR '(' I '=' ZERO ';' I '<' FOUR ';' I '=' I '+' ONE ')' '{'
          A '[' I ']' '=' TRANSFORM '(' A '[' I ']' ',' X ')' ';'
          IF '(' A '[' I ']' '>' threshold ')' BREAK ';'
        '}'
        Y '=' SUM '(' A ',' FOUR ')' ';'
        PRINTF '(' formatTwo ',' X ',' Y ')' ';'
        RETURN ZERO ';'
      '}'
    ;

mixedGlobals
    : CONST INT C '=' nonZero ';'
    | INT G '=' number ';'
    | CONST INT C '=' nonZero ';' INT G '=' number ';'
    ;

scalarDecl
    : INT X '=' number ',' Y '=' nonZero ',' I '=' ZERO ';'
    | INT X '=' number ';' INT Y '=' nonZero ';' INT I '=' ZERO ';'
    | INT X '=' number ',' Y '=' nonZero ';' INT I '=' ZERO ';'
    ;

scalarStmt
    : X '=' safeExprXY ';'
    | Y '=' safeExprXY ';'
    | '{' INT Z '=' safeExprXY ';' X '=' Z addOp nonZero ';' '}'
    | PRINTF '(' formatOne ',' safeExprXY ')' ';'
    ;

controlStmt
    : boundedFor
    | conditional
    | boundedFor conditional
    | conditional boundedFor
    ;

boundedFor
    : FOR '(' I '=' ZERO ';' I '<' bound ';' I '=' I '+' ONE ')' '{' X '=' X '+' I ';' '}'
    | FOR '(' ';' I '<' bound ';' I '=' I '+' ONE ')' '{' Y '=' Y addOp ONE ';' '}'
    | FOR '(' I '=' ZERO ';' ';' I '=' I '+' ONE ')' '{' IF '(' I '>=' bound ')' BREAK ';' X '=' X '+' ONE ';' '}'
    | FOR '(' I '=' ZERO ';' I '<' bound ';' ')' '{' I '=' I '+' ONE ';' IF '(' I '==' TWO ')' CONTINUE ';' Y '=' Y '+' I ';' '}'
    ;

conditional
    : IF '(' condition ')' scalarStmt
    | IF '(' condition ')' '{' scalarStmt '}' ELSE '{' scalarStmt '}'
    | IF '(' condition ')' IF '(' X relation nonZero ')' scalarStmt ELSE scalarStmt
    ;

condition
    : X relation Y
    | X relation nonZero logicOp Y relation nonZero
    | '!' X logicOp Y relation nonZero
    ;

arrayStmt
    : A '[' index ']' '=' X addOp nonZero ';'
    | X '=' A '[' index ']' mulOp nonZero ';'
    | A '[' index ']' '=' A '[' otherIndex ']' addOp Y ';'
    | Y '=' A '[' index ']' addOp A '[' otherIndex ']' ';'
    ;

arrayOutput
    : PRINTF '(' formatOne ',' A '[' index ']' ')' ';'
    | PRINTF '(' formatTwo ',' A '[' index ']' ',' A '[' otherIndex ']' ')' ';'
    | PRINTF '(' formatTwo ',' X ',' Y ')' ';'
    ;

scalarOutput
    : PRINTF '(' formatOne ',' X ')' ';'
    | PRINTF '(' formatTwo ',' X ',' Y ')' ';'
    | PRINTF '(' formatOne ',' safeExprXY ')' ';'
    ;

safeExprXY
    : X
    | Y
    | number
    | X addOp Y
    | X '*' Y
    | X '/' nonZero
    | X '%' nonZero
    | '(' X addOp Y ')' mulOp nonZero
    | '-' X
    ;

safeExprPQ
    : P
    | Q
    | number
    | P addOp Q
    | P '*' Q
    | P '/' nonZero
    | P '%' nonZero
    | '(' P addOp Q ')' mulOp nonZero
    ;

relation
    : '<' | '>' | '<=' | '>=' | '==' | '!='
    ;

logicOp
    : '&&' | '||'
    ;

addOp
    : '+' | '-'
    ;

mulOp
    : '*' | '/' | '%'
    ;

index
    : ZERO | ONE | TWO | THREE
    ;

otherIndex
    : ZERO | ONE | TWO | THREE
    ;

smallBound
    : THREE | FOUR | FIVE | SIX
    ;

bound
    : TWO | THREE | FOUR | FIVE | SIX | nonZero
    ;

threshold
    : nonZero
    | '1000'
    ;

zeroOrPositive
    : ZERO | nonZero
    ;

formatOne
    : FORMAT_ONE
    ;

formatTwo
    : FORMAT_TWO
    ;

number
    : ZERO | ONE | TWO | THREE | FOUR | FIVE | SIX | nonZero
    ;

nonZero
    : POSITIVE
    ;

CONST: 'const ';
STATIC: 'static ';
INT: 'int ';
MAIN: 'main';
IF: 'if';
ELSE: 'else ';
FOR: 'for';
BREAK: 'break';
CONTINUE: 'continue';
RETURN: 'return ';
PRINTF: 'printf';
GETINT: 'getint';
SUM: 'sum';
TRANSFORM: 'transform';
SIDE: 'side';
NEXT: 'next';
FIB: 'fib';
FACT: 'fact';
COUNTDOWN: 'countdown';
COMBINE: 'combine';
C: 'c';
G: 'g';
A: 'a';
N: 'n';
I: 'i';
TOTAL: 'total';
STATE: 'state';
X: 'x';
Y: 'y';
Z: 'z';
P: 'p';
Q: 'q';
R: 'r';
ZERO: '0';
ONE: '1';
TWO: '2';
THREE: '3';
FOUR: '4';
FIVE: '5';
SIX: '6';
AND: '&&';
OR: '||';
FORMAT_ONE: '"%d"' | '"%d\\n"' | '"value=%d\\n"' | '"[%d]"';
FORMAT_TWO: '"%d %d\\n"' | '"pair=%d,%d\\n"' | '"%d:%d"';
POSITIVE: [7-9] | [1-9] [0-9] | [1-9] [0-9] [0-9];
WS: [ \t\r\n]+ -> skip;
