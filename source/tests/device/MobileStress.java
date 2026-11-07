package org.esurfing.hunan;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
public class MobileStress {
 public static void main(String[] args) throws Exception {
  NativeCore core=new NativeCore(); byte[] module=Files.readAllBytes(Paths.get(args[0]));
  if(core.createMobile(new byte[2])!=0)throw new AssertionError("bad module");
  for(int i=0;i<100;i++) {
   long id=core.createMobile(module);if(id==0 || core.mobileId(id)==null)throw new AssertionError("create");
   for(String s:new String[]{"A","A".repeat(15),"A".repeat(16),"A".repeat(17),"A".repeat(384),"中文😀"}) {
    byte[] b=s.getBytes(StandardCharsets.UTF_8),enc=core.cryptMobile(id,b,false);
    if(enc==null || !Arrays.equals(b,core.cryptMobile(id,enc,true)))throw new AssertionError("roundtrip");
   }
   core.releaseMobile(id);core.releaseMobile(id);
   if(core.cryptMobile(id,new byte[]{65},false)!=null)throw new AssertionError("stale handle");
  }
  long[] handles=new long[8];for(int i=0;i<8;i++){handles[i]=core.createMobile(module);if(handles[i]==0)throw new AssertionError("slot leak");}
  if(core.createMobile(module)!=0)throw new AssertionError("capacity");for(long h:handles)core.releaseMobile(h);
  long shared=core.createMobile(module);
  var failure=new java.util.concurrent.atomic.AtomicReference<Throwable>();Thread[] workers=new Thread[4];
  for(int k=0;k<4;k++){workers[k]=new Thread(()->{try{for(int i=0;i<1000;i++){
   byte[] b=("parallel-"+i).getBytes(StandardCharsets.UTF_8);byte[] enc=core.cryptMobile(shared,b,false);
   if(!Arrays.equals(b,core.cryptMobile(shared,enc,true)))throw new AssertionError("parallel");
  }}catch(Throwable t){failure.set(t);}});workers[k].start();}
  for(Thread t:workers)t.join();core.releaseMobile(shared);if(failure.get()!=null)throw new AssertionError(failure.get());
  long racing=core.createMobile(module);Thread t=new Thread(()->{try{for(int i=0;i<10000;i++)if(core.cryptMobile(racing,new byte[]{65},false)==null)break;}catch(Throwable e){failure.set(e);}});
  t.start();core.releaseMobile(racing);t.join();if(failure.get()!=null)throw new AssertionError(failure.get());
  long next=core.createMobile(module);if(next==0)throw new AssertionError("restart after release");core.releaseMobile(next);
  System.out.println("PASS: 100 create/release cycles, UTF-8 and block boundaries, stale handles, capacity recovery, 4000 parallel roundtrips, concurrent release and restart");
 }
}
