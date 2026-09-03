grammar SysY_4to5;

// Assignment 4: compositional, executable SysY programs covering constants,
// variables, input, arithmetic, functions, arrays, and mixed combinations.
compUnit
    : constProgram EOF
    | variableProgram EOF
    | inputProgram EOF
    | arithmeticProgram EOF
    | functionProgram EOF
    | arrayProgram EOF
    | completeProgram EOF
    ;

constProgram
    : constGlobals INT MAIN '(' ')' '{' constLocal? constOutput constOutput? RETURN ZERO ';' '}'
    ;

constGlobals
    : CONST INT C '=' nonZero ';'
    | CONST INT C '=' nonZero ',' D '=' constExpr ';'
    | CONST INT C '=' nonZero ';' CONST INT CA '[' FOUR ']' '=' '{' number ',' number ',' number ',' number '}' ';'
    ;

constLocal
    : CONST INT LC '=' constExpr ';'
    | CONST INT LA '[' FOUR ']' '=' '{' number ',' number ',' number ',' number '}' ';'
    ;

constOutput
    : PRINTF '(' formatOne ',' C ')' ';'
    | PRINTF '(' formatOne ',' constExpr ')' ';'
    | PRINTF '(' formatTwo ',' C ',' constExpr ')' ';'
    | PRINTF '(' plainString ')' ';'
    ;

variableProgram
    : variableGlobals? INT MAIN '(' ')' '{' scalarDecl scalarStmt scalarStmt? scalarOutput RETURN ZERO ';' '}'
    ;

variableGlobals
    : INT G ';'
    | INT G '=' number ';'
    | INT G '=' number ',' H '=' nonZero ';'
    ;

inputProgram
    : calcFunction INT MAIN '(' ')' '{' inputDecl inputWork inputWork? inputOutput RETURN ZERO ';' '}'
    ;

inputDecl
    : INT X '=' GETINT '(' ')' ';' INT Y '=' number ';'
    | INT X ';' X '=' GETINT '(' ')' ';' INT Y '=' nonZero ';'
    | INT X '=' GETINT '(' ')' ',' Y '=' GETINT '(' ')' ';'
    | INT A '[' FOUR ']' '=' '{' number ',' number ',' number ',' number '}' ';' INT X '=' GETINT '(' ')' ';' INT Y '=' number ';'
    ;

inputWork
    : X '=' safeExprXY ';'
    | Y '=' safeExprXY ';'
    | X '=' X '*' nonZero ';'
    | Y '=' Y addOp X ';'
    | X '=' CALC '(' X ',' Y ')' ';'
    ;

inputOutput
    : PRINTF '(' formatOne ',' X ')' ';'
    | PRINTF '(' formatTwo ',' X ',' Y ')' ';'
    | PRINTF '(' formatOne ',' safeExprXY ')' ';'
    | PRINTF '(' formatOne ',' CALC '(' X ',' Y ')' ')' ';'
    ;

arithmeticProgram
    : INT MAIN '(' ')' '{' scalarDecl INT Z '=' safeExprXY ';' arithmeticStmt arithmeticStmt? PRINTF '(' formatOne ',' Z ')' ';' RETURN ZERO ';' '}'
    ;

arithmeticStmt
    : Z '=' safeExprXYZ ';'
    | X '=' safeExprXY ';'
    | Y '=' '(' X addOp Y ')' mulOp nonZero ';'
    | Z '=' Z addOp X ';'
    | X '=' X mulOp nonZero ';'
    ;

functionProgram
    : helperFunctions INT MAIN '(' ')' '{' scalarDecl functionCall functionCall? scalarOutput RETURN ZERO ';' '}'
    ;

helperFunctions
    : calcFunction unaryFunction showFunction
    | calcFunction showFunction unaryFunction
    ;

calcFunction
    : INT CALC '(' INT P ',' INT Q ')' '{' RETURN safeExprPQ ';' '}'
    ;

unaryFunction
    : INT INC '(' INT P ')' '{' RETURN P addOp nonZero ';' '}'
    ;

showFunction
    : VOID SHOW '(' INT P ')' '{' PRINTF '(' formatOne ',' P ')' ';' RETURN ';' '}'
    ;

functionCall
    : X '=' CALC '(' X ',' Y ')' ';'
    | Y '=' INC '(' X ')' ';'
    | SHOW '(' safeExprXY ')' ';'
    | PRINTF '(' formatOne ',' CALC '(' X ',' Y ')' ')' ';'
    | X '=' CALC '(' Y ',' X ')' ';'
    ;

arrayProgram
    : calcFunction arrayGlobal? INT MAIN '(' ')' '{' arrayLocal arrayStmt arrayStmt? arrayOutput RETURN ZERO ';' '}'
    ;

arrayGlobal
    : INT GA '[' FOUR ']' '=' '{' number ',' number ',' number ',' number '}' ';'
    | CONST INT CA '[' FOUR ']' '=' '{' number ',' number ',' number ',' number '}' ';'
    ;

arrayLocal
    : INT A '[' FOUR ']' '=' '{' number ',' number ',' number ',' number '}' ';' INT X '=' number ';'
    | INT A '[' FOUR ']' '=' '{' number ',' number ',' number ',' number '}' ';' INT X '=' number ';' A '[' ZERO ']' '=' number ';' A '[' ONE ']' '=' nonZero ';'
    ;

arrayStmt
    : A '[' index ']' '=' X addOp nonZero ';'
    | X '=' A '[' index ']' mulOp nonZero ';'
    | A '[' index ']' '=' A '[' otherIndex ']' addOp X ';'
    | X '=' A '[' index ']' addOp A '[' otherIndex ']' ';'
    | A '[' index ']' '=' CALC '(' X ',' X ')' ';'
    ;

arrayOutput
    : PRINTF '(' formatOne ',' A '[' index ']' ')' ';'
    | PRINTF '(' formatTwo ',' A '[' index ']' ',' A '[' otherIndex ']' ')' ';'
    | PRINTF '(' formatTwo ',' X ',' A '[' index ']' ')' ';'
    | PRINTF '(' formatOne ',' X ')' ';'
    ;

completeProgram
    : CONST INT C '=' nonZero ';'
      INT CALC '(' INT P ',' INT Q ')' '{' RETURN safeExprPQ ';' '}'
      INT INC '(' INT P ')' '{' RETURN P addOp nonZero ';' '}'
      INT MAIN '(' ')' '{'
        INT A '[' FOUR ']' '=' '{' number ',' number ',' number ',' number '}' ';'
        INT X '=' number ',' Y '=' nonZero ';'
        X '=' GETINT '(' ')' ';'
        A '[' index ']' '=' CALC '(' X ',' Y ')' ';'
        Y '=' INC '(' X ')' ';'
        PRINTF '(' formatTwo ',' X ',' A '[' otherIndex ']' ')' ';'
        RETURN ZERO ';'
      '}'
    | INT MAIN '(' ')' '{'
        CONST INT C '=' nonZero ';'
        INT X '=' number ',' Y '=' nonZero ',' Z '=' number ';'
        X '=' safeExprXY ';' Y '=' safeExprXY ';'
        PRINTF '(' formatTwo ',' X ',' Y ')' ';'
        RETURN ZERO ';'
      '}'
    | INT GA '[' FOUR ']' '=' '{' number ',' number ',' number ',' number '}' ';'
      INT MAIN '(' ')' '{'
        INT X '=' number ';' INT Y '=' nonZero ';'
        X '=' GA '[' index ']' addOp nonZero ';'
        PRINTF '(' formatTwo ',' X ',' GA '[' otherIndex ']' ')' ';'
        RETURN ZERO ';'
      '}'
    ;

scalarDecl
    : INT X '=' number ',' Y '=' nonZero ';'
    | INT X '=' number ';' INT Y '=' nonZero ';'
    | INT X '=' number ',' Y '=' nonZero ',' Z '=' number ';'
    ;

scalarStmt
    : X '=' safeExprXY ';'
    | Y '=' safeExprXY ';'
    | '{' INT Z '=' safeExprXY ';' X '=' Z addOp nonZero ';' '}'
    | PRINTF '(' formatOne ',' safeExprXY ')' ';'
    ;

scalarOutput
    : PRINTF '(' formatOne ',' X ')' ';'
    | PRINTF '(' formatTwo ',' X ',' Y ')' ';'
    | PRINTF '(' formatOne ',' safeExprXY ')' ';'
    ;

constExpr
    : C | number | C addOp nonZero | nonZero mulOp nonZero
    ;

safeExprXY
    : X | Y | number | X addOp Y | X '*' Y | X '/' nonZero | X '%' nonZero
    | '(' X addOp Y ')' '*' nonZero | '-' X
    ;

safeExprXYZ
    : Z addOp X | Z '*' nonZero | '(' X addOp Y ')' mulOp nonZero | X addOp Y addOp Z
    ;

safeExprPQ
    : P | Q | number | P addOp Q | P '*' Q | P '/' nonZero | P '%' nonZero
    | '(' P addOp Q ')' mulOp nonZero
    ;

addOp : '+' | '-' ;
mulOp : '*' | '/' | '%' ;
index : ZERO | ONE | TWO | THREE ;
otherIndex : ZERO | ONE | TWO | THREE ;
formatOne : FORMAT_ONE ;
formatTwo : FORMAT_TWO ;
plainString : PLAIN_STRING ;
number : ZERO | ONE | TWO | THREE | FOUR | nonZero ;
nonZero : POSITIVE ;

CONST: 'const ';
INT: 'int ';
VOID: 'void ';
MAIN: 'main';
RETURN: 'return ';
PRINTF: 'printf';
GETINT: 'getint';
CALC: 'calc';
INC: 'inc';
SHOW: 'show';
C: 'c'; D: 'd'; LC: 'lc'; LA: 'la'; CA: 'ca';
G: 'g'; H: 'h'; GA: 'ga'; X: 'x'; Y: 'y'; Z: 'z'; P: 'p'; Q: 'q'; A: 'a';
ZERO: '0'; ONE: '1'; TWO: '2'; THREE: '3'; FOUR: '4';
FORMAT_ONE: '"%d"' | '"%d\\n"' | '"value=%d\\n"' | '"[%d]"' | '"result=%d"';
FORMAT_TWO: '"%d %d\\n"' | '"pair=%d,%d\\n"' | '"%d:%d"' | '"left=%d right=%d\\n"';
PLAIN_STRING: '"ok\\n"' | '"constants\\n"';
POSITIVE: [5-9] | [1-9] [0-9] | [1-9] [0-9] [0-9];
WS: [ \t\r\n]+ -> skip;
