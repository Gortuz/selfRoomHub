import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.content.AttributionSource;
import android.content.Context;
import android.content.ContextWrapper;
import android.os.IBinder;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.Method;

/**
 * Conecta o desconecta un dispositivo Bluetooth clásico sin interfaz, y consulta su estado.
 * Debe ejecutarse como el usuario shell de Android (tiene BLUETOOTH_PRIVILEGED), p. ej. con rish:
 *   CLASSPATH=btctl.dex app_process / BtCtl connect|disconnect|status AA:BB:CC:DD:EE:FF
 * Salida (una línea): "status true|false", "connect <código>" o "disconnect <código>"; 0 = éxito.
 */
public class BtCtl {
    static final String PKG = "com.android.shell";

    static class ShellContext extends ContextWrapper {
        ShellContext(Context base) { super(base); }
        @Override public String getPackageName() { return PKG; }
        @Override public String getOpPackageName() { return PKG; }
        @Override public AttributionSource getAttributionSource() { return source(); }
        @Override public Context getApplicationContext() { return this; }
    }

    static AttributionSource source() {
        return new AttributionSource.Builder(android.os.Process.myUid()).setPackageName(PKG).build();
    }

    static Context systemContext() throws Exception {
        Class<?> atc = Class.forName("android.app.ActivityThread");
        Constructor<?> ctor = atc.getDeclaredConstructor();
        ctor.setAccessible(true);
        Object at = ctor.newInstance();
        Field cur = atc.getDeclaredField("sCurrentActivityThread");
        cur.setAccessible(true);
        cur.set(null, at);
        Field sys = atc.getDeclaredField("mSystemThread");
        sys.setAccessible(true);
        sys.setBoolean(at, true);
        return (Context) atc.getDeclaredMethod("getSystemContext").invoke(at);
    }

    static BluetoothAdapter adapter() throws Exception {
        Context ctx = new ShellContext(systemContext());
        IBinder binder = (IBinder) Class.forName("android.os.ServiceManager")
                .getMethod("getService", String.class).invoke(null, "bluetooth_manager");
        Class<?> ibm = Class.forName("android.bluetooth.IBluetoothManager");
        Object manager = Class.forName("android.bluetooth.IBluetoothManager$Stub")
                .getMethod("asInterface", IBinder.class).invoke(null, binder);
        Constructor<BluetoothAdapter> c = BluetoothAdapter.class
                .getDeclaredConstructor(ibm, Context.class, AttributionSource.class);
        c.setAccessible(true);
        return c.newInstance(manager, ctx, source());
    }

    public static void main(String[] args) throws Exception {
        android.os.Looper.prepareMainLooper();
        // Lo hace ActivityThread al arrancar una app: registra los servicios de los módulos (Bluetooth incluido)
        Class.forName("android.app.ActivityThread").getMethod("initializeMainlineModules").invoke(null);
        BluetoothAdapter adapter = adapter();
        // BluetoothDevice usa internamente el adaptador por defecto (estático); en app_process está vacío
        Field def = BluetoothAdapter.class.getDeclaredField("sAdapter");
        def.setAccessible(true);
        def.set(null, adapter);
        BluetoothDevice device = adapter.getRemoteDevice(args[1]);
        Object result = args[0].equals("status")
                ? BluetoothDevice.class.getMethod("isConnected").invoke(device)
                : BluetoothDevice.class.getMethod(args[0]).invoke(device);
        System.out.println(args[0] + " " + result);
        System.exit(0);
    }
}
