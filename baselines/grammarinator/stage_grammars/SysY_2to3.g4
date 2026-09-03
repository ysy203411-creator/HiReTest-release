grammar SysY_2to3;

// Assignment 2: compositional valid syntax plus one controlled i/j/k error.
compUnit
    : validProgram EOF
    | leadingLines? missingSemicolonProgram EOF
    | leadingLines? missingRightParenProgram EOF
    | leadingLines? missingRightBracketProgram EOF
    ;

validProgram
    : scalarProgram
    | arrayProgram
    | functionProgram
    | controlProgram
    ;

scalarProgram
    : globalDecl?
      INT MAIN '(' ')' '{'
        INT X '=' number ',' Y '=' nonZero ';'
        scalarStmt scalarStmt? scalarIf?
        RETURN ZERO ';'
      '}'
    ;

arrayProgram
    : INT MAIN '(' ')' '{'
        INT A '[' FOUR ']' '=' '{' number ',' number ',' number ',' number '}' ';'
        INT X '=' number ',' Y '=' nonZero ';'
        arrayStmt arrayStmt? arrayIf?
        RETURN ZERO ';'
      '}'
    ;

functionProgram
    : INT ADD '(' INT LEFT ',' INT RIGHT ')' '{' RETURN scalarExprParam ';' '}'
      VOID SHOW '(' INT PARAM ')' '{' PRINTF '(' formatOne ',' PARAM ')' ';' RETURN ';' '}'
      INT MAIN '(' ')' '{'
        INT X '=' number ',' Y '=' nonZero ';'
        X '=' ADD '(' scalarExpr ',' scalarExpr ')' ';'
        SHOW '(' X ')' ';'
        scalarStmt?
        RETURN ZERO ';'
      '}'
    ;

controlProgram
    : INT MAIN '(' ')' '{'
        INT I '=' ZERO ',' X '=' number ';'
        loopStmt
        scalarIf?
        RETURN ZERO ';'
      '}'
    ;

globalDecl
    : CONST INT C '=' nonZero ';'
    | INT G '=' number ';'
    | CONST INT C '=' nonZero ';' INT G '=' number ';'
    ;

scalarStmt
    : X '=' scalarExpr ';'
    | Y '=' scalarExpr ';'
    | PRINTF '(' formatOne ',' scalarExpr ')' ';'
    | '{' X '=' scalarExpr ';' PRINTF '(' formatOne ',' X ')' ';' '}'
    ;

arrayStmt
    : A '[' index ']' '=' scalarExpr ';'
    | X '=' A '[' index ']' addOp nonZero ';'
    | PRINTF '(' formatTwo ',' A '[' index ']' ',' X ')' ';'
    | '{' A '[' index ']' '=' A '[' index ']' addOp nonZero ';' '}'
    ;

scalarIf
    : IF '(' condition ')' scalarStmt
    | IF '(' condition ')' '{' scalarStmt '}' ELSE '{' scalarStmt '}'
    ;

arrayIf
    : IF '(' A '[' index ']' relation X ')' arrayStmt
    | IF '(' A '[' index ']' relation nonZero ')' '{' arrayStmt '}' ELSE '{' scalarStmt '}'
    ;

loopStmt
    : FOR '(' I '=' ZERO ';' I '<' bound ';' I '=' I '+' ONE ')' '{' X '=' X '+' I ';' '}'
    | FOR '(' ';' I '<' bound ';' I '=' I '+' ONE ')' '{' X '=' X '+' ONE ';' '}'
    | FOR '(' I '=' ZERO ';' ';' I '=' I '+' ONE ')' '{' IF '(' I '>=' bound ')' BREAK ';' '}'
    | FOR '(' I '=' ZERO ';' I '<' bound ';' ')' '{' I '=' I '+' ONE ';' CONTINUE ';' '}'
    ;

condition
    : scalarExpr relation scalarExpr
    | scalarExpr relation nonZero logicOp scalarExpr relation nonZero
    ;

scalarExpr
    : atom
    | atom addOp atom
    | atom mulOp safeAtom
    | '(' atom addOp atom ')' mulOp safeAtom
    | '+' atom
    | '-' atom
    ;

scalarExprParam
    : LEFT
    | RIGHT
    | LEFT addOp RIGHT
    | LEFT mulOp RIGHT
    | '(' LEFT addOp RIGHT ')' mulOp nonZero
    ;

atom
    : X
    | Y
    | number
    ;

safeAtom
    : X
    | Y
    | nonZero
    ;

missingSemicolonProgram
    : missingDeclSemicolon
    | missingAssignSemicolon
    | missingReturnSemicolon
    | missingPrintfSemicolon
    ;

missingDeclSemicolon
    : INT MAIN '(' ')' '{' NL INT X '=' number SP NL X '=' X '+' ONE ';' NL RETURN ZERO ';' NL '}'
    ;

missingAssignSemicolon
    : INT MAIN '(' ')' '{' NL INT X '=' number ',' Y '=' nonZero ';' NL X '=' scalarExpr SP NL PRINTF '(' formatOne ',' X ')' ';' NL RETURN ZERO ';' NL '}'
    ;

missingReturnSemicolon
    : INT MAIN '(' ')' '{' NL INT X '=' number ';' NL RETURN ZERO NL '}'
    ;

missingPrintfSemicolon
    : INT MAIN '(' ')' '{' NL INT X '=' number ';' NL PRINTF '(' formatOne ',' X ')' SP NL RETURN ZERO ';' NL '}'
    ;

missingRightParenProgram
    : missingIfParen
    | missingCallParen
    | missingMainParen
    | missingPrimaryParen
    ;

missingIfParen
    : INT MAIN '(' ')' '{' NL INT X '=' number ',' Y '=' nonZero ';' NL IF '(' condition '{' X '=' X '+' ONE ';' '}' NL RETURN ZERO ';' NL '}'
    ;

missingCallParen
    : INT ADD '(' INT LEFT ',' INT RIGHT ')' '{' RETURN LEFT '+' RIGHT ';' '}'
      NL INT MAIN '(' ')' '{' NL INT X '=' ADD '(' number ',' nonZero ';' NL RETURN ZERO ';' NL '}'
    ;

missingMainParen
    : INT MAIN '(' NL '{' NL RETURN ZERO ';' NL '}'
    ;

missingPrimaryParen
    : INT MAIN '(' ')' '{' NL INT X '=' '(' number addOp nonZero ';' NL RETURN ZERO ';' NL '}'
    ;

missingRightBracketProgram
    : missingArrayDeclBracket
    | missingArrayAccessBracket
    | missingArrayParamBracket
    ;

missingArrayDeclBracket
    : INT MAIN '(' ')' '{' NL INT A '[' FOUR '=' '{' number ',' number ',' number ',' number '}' ';' NL RETURN ZERO ';' NL '}'
    ;

missingArrayAccessBracket
    : INT MAIN '(' ')' '{' NL INT A '[' FOUR ']' '=' '{' number ',' number ',' number ',' number '}' ';' NL PRINTF '(' formatOne ',' A '[' index ')' ';' NL RETURN ZERO ';' NL '}'
    ;

missingArrayParamBracket
    : INT FIRST '(' INT A '[' ')' '{' RETURN A '[' ZERO ']' ';' '}' NL
      INT MAIN '(' ')' '{' NL INT A '[' FOUR ']' '=' '{' number ',' number ',' number ',' number '}' ';' NL RETURN FIRST '(' A ')' ';' NL '}'
    ;

relation
    : '<'
    | '>'
    | '<='
    | '>='
    | '=='
    | '!='
    ;

logicOp
    : '&&'
    | '||'
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

index
    : ZERO
    | ONE
    | TWO
    | THREE
    ;

bound
    : TWO
    | THREE
    | FOUR
    | nonZero
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
ELSE: 'else ';
FOR: 'for';
BREAK: 'break';
CONTINUE: 'continue';
RETURN: 'return ';
PRINTF: 'printf';
C: 'c';
G: 'g';
ADD: 'add';
SHOW: 'show';
FIRST: 'first';
LEFT: 'left';
RIGHT: 'right';
PARAM: 'param';
X: 'x';
Y: 'y';
A: 'a';
I: 'i';
ZERO: '0';
ONE: '1';
TWO: '2';
THREE: '3';
FOUR: '4';
FORMAT_ONE: '"%d"' | '"%d\\n"' | '"result=%d\\n"' | '"[%d]"';
FORMAT_TWO: '"%d %d\\n"' | '"pair=%d,%d\\n"' | '"%d:%d"';
POSITIVE: [5-9] | [1-9] [0-9] | [1-9] [0-9] [0-9];
SP: ' ';
NL: '\n';
WS: [ \t\r]+ -> skip;
