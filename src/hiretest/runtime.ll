; runtime.ll - IO runtime for compiler course (LLVM 12.0.0 compatible)
; Provides definitions for: getint,  putint, putch, putstr(getchar is moved)

@.str_int = private constant [3 x i8] c"%d\00"
@.str_char = private constant [3 x i8] c"%c\00"

; External C library functions (must be declared)
declare i32 @scanf(i8*, ...)
declare i32 @printf(i8*, ...)

; getint(): reads an integer from stdin
define i32 @getint() {
entry:
  %x = alloca i32, align 4
  %fmt = getelementptr inbounds [3 x i8], [3 x i8]* @.str_int, i32 0, i32 0
  %ret = call i32 (i8*, ...) @scanf(i8* %fmt, i32* %x)
  %val = load i32, i32* %x, align 4
  ret i32 %val
}


; putint(i32): prints an integer to stdout
define void @putint(i32 %n) {
entry:
  %fmt = getelementptr inbounds [3 x i8], [3 x i8]* @.str_int, i32 0, i32 0
  call i32 (i8*, ...) @printf(i8* %fmt, i32 %n)
  ret void
}

; putch(i32): prints a character (lower 8 bits) to stdout
define void @putch(i32 %c) {
entry:
  %ch = trunc i32 %c to i8
  %fmt = getelementptr inbounds [3 x i8], [3 x i8]* @.str_char, i32 0, i32 0
  call i32 (i8*, ...) @printf(i8* %fmt, i8 %ch)
  ret void
}

; putstr(i8*): prints a null-terminated string to stdout
define void @putstr(i8* %str) {
entry:
  call i32 (i8*, ...) @printf(i8* %str)
  ret void
}