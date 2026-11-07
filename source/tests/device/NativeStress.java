package org.esurfing.hunan;

class NativeCore {
    static { System.load(System.getProperty("hunan.library")); }
    native String crypt(String input, boolean decrypt);
    native String xml(int endpoint, String[] values);
    native long createMobile(byte[] module);
    native String mobileId(long handle);
    native byte[] cryptMobile(long handle, byte[] input, boolean decrypt);
    native void releaseMobile(long handle);
}

public class NativeStress {
    public static void main(String[] args) throws Exception {
        var core = new NativeCore();
        var samples = java.nio.file.Files.readAllLines(java.nio.file.Paths.get(args[0]));
        for (int i=0;i<samples.size();i++) {
            String cipher=samples.get(i).trim();
            String plain=core.crypt(cipher,true);
            if(plain==null || !cipher.equalsIgnoreCase(core.crypt(plain,false)))
                throw new AssertionError("official sample " + i);
        }
        System.out.println("PASS: " + samples.size() + " captured samples, decrypt/re-encrypt byte equality; no plaintext output");
        for (int length : new int[]{0, 1, 15, 16, 17, 31, 32, 384, 4096}) {
            String text = "A".repeat(length);
            String wire = core.crypt(text, false);
            int expected = 2 * (32 + ((length + 1 + 15) / 16) * 16);
            if (wire == null || wire.length() != expected || !text.equals(core.crypt(wire, true)))
                throw new AssertionError("padding/roundtrip length=" + length);
        }
        String xml = core.xml(2, new String[]{"00000000k", "TICKET", "CLIENT", "UA"});
        String expected = "<?xml version=\"1.0\" encoding=\"utf-8\"?><request>\n<local-time>00000000k</local-time>\n<ticket>TICKET</ticket>\n<client-id>CLIENT</client-id>\n<user-agent>UA</user-agent>\n</request>";
        if (!expected.equals(xml)) throw new AssertionError("XML field ordering");
        if (core.xml(99, new String[]{}) != null || core.xml(2, new String[]{}) != null)
            throw new AssertionError("invalid endpoint/count");
        var threads = new Thread[4];
        var failure = new java.util.concurrent.atomic.AtomicReference<Throwable>();
        for(int n=0;n<threads.length;n++) {
            threads[n] = new Thread(() -> { try {
                for(int i=0;i<1000;i++) {
                    String text="JNI-"+i;
                    if(!text.equals(core.crypt(core.crypt(text,false),true))) throw new AssertionError("concurrency");
                }
            } catch(Throwable t) { failure.set(t); } });
            threads[n].start();
        }
        for(var thread:threads) thread.join();
        if(failure.get()!=null) throw new AssertionError(failure.get());
        System.out.println("PASS: padding boundaries, exact XML order, invalid arguments, 4000 concurrent JNI calls");
    }
}


