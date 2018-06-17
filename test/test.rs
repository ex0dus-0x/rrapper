fn foo<'a>(input: *const u32) -> &'a u32 {
    unsafe {
        return &*input;
    }
}

fn main(){
    let x;
    {
        let y = 7;
        x = foo(&y);
    }
    
    // unexpected behavior HERE
    println!("{}", x);

}
