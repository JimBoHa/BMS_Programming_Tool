/* Copyright 2026 BMS Studio contributors. SPDX-License-Identifier: Apache-2.0 */
import java.net.InetAddress;
import java.util.HashSet;
import javax.xml.parsers.DocumentBuilderFactory;
import javax.xml.stream.XMLOutputFactory;
import javax.xml.stream.XMLStreamWriter;
import org.w3c.dom.Element;
import org.w3c.dom.Node;
import sedona.Component;
import sedona.Kit;
import sedona.Link;
import sedona.Schema;
import sedona.Slot;
import sedona.Type;
import sedona.Value;
import sedona.dasp.DaspSocket;
import sedona.sox.SoxClient;
import sedona.sox.SoxComponent;

/** Small stdin/stdout bridge to the upstream Sedona Java API. No shell or script evaluation. */
public final class SoxBridge {
  private static SoxComponent find(SoxClient client, String path) throws Exception {
    if (!path.startsWith("/")) throw new IllegalArgumentException("Absolute component path required");
    SoxComponent component = client.loadApp();
    for (String name : path.split("/")) {
      if (name.isEmpty()) continue;
      client.update(component, SoxComponent.TREE);
      component = component.child(name);
      if (component == null) throw new IllegalArgumentException("Component not found: " + path);
    }
    return component;
  }

  private static void attr(XMLStreamWriter out, String key, Object value) throws Exception {
    out.writeAttribute(key, String.valueOf(value));
  }

  private static void snapshot(SoxClient client, SoxComponent c, XMLStreamWriter out,
                               HashSet<Integer> visited, int depth) throws Exception {
    if (depth > 24 || visited.size() >= 2048 || !visited.add(c.id()))
      throw new IllegalArgumentException("Component tree exceeds inventory limit");
    client.update(c, SoxComponent.TREE | SoxComponent.CONFIG | SoxComponent.RUNTIME | SoxComponent.LINKS);
    out.writeStartElement("component");
    attr(out, "id", c.id()); attr(out, "name", c.name()); attr(out, "type", c.type.qname);
    for (Slot slot : c.type.slots) {
      if (!slot.isProp() || slot.name.equals("cred")) continue;
      out.writeEmptyElement("property");
      attr(out, "id", slot.id);
      attr(out, "name", slot.name); attr(out, "type", slot.type.qname);
      attr(out, "config", slot.isConfig());
      attr(out, "value", c.get(slot).encodeString());
    }
    for (Link link : client.links(c)) {
      if (link.fromCompId != c.id()) continue;
      out.writeEmptyElement("link");
      attr(out, "from", link.fromCompId); attr(out, "from_slot", link.fromSlotId);
      attr(out, "to", link.toCompId); attr(out, "to_slot", link.toSlotId);
    }
    for (SoxComponent child : c.children()) snapshot(client, child, out, visited, depth + 1);
    out.writeEndElement();
  }

  public static void main(String[] args) throws Exception {
    // Credentials travel only over stdin; they never appear in process arguments or stdout.
    DocumentBuilderFactory factory = DocumentBuilderFactory.newInstance();
    factory.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true);
    factory.setFeature("http://xml.org/sax/features/external-general-entities", false);
    factory.setFeature("http://xml.org/sax/features/external-parameter-entities", false);
    factory.setXIncludeAware(false); factory.setExpandEntityReferences(false);
    Element request = factory.newDocumentBuilder().parse(System.in).getDocumentElement();
    DaspSocket socket = DaspSocket.open(-1, null, DaspSocket.SESSION_QUEUING);
    SoxClient client = new SoxClient(socket, InetAddress.getByName(request.getAttribute("host")),
        Integer.parseInt(request.getAttribute("port")), request.getAttribute("user"),
        request.getAttribute("password"));
    XMLStreamWriter out = XMLOutputFactory.newFactory().createXMLStreamWriter(System.out, "UTF-8");
    try {
      client.connect();
      Schema schema = client.readSchema();
      out.writeStartDocument(); out.writeStartElement("result");
      attr(out, "platform", client.readVersion().platformId);
      for (Node node = request.getFirstChild(); node != null; node = node.getNextSibling()) {
        if (!(node instanceof Element)) continue;
        Element operation = (Element)node;
        String command = operation.getTagName();
        SoxComponent c = find(client, operation.getAttribute("path"));
        if (command.equals("inventory")) {
          snapshot(client, c, out, new HashSet<Integer>(), 0);
          continue;
        }
        if (command.equals("read")) {
          out.writeEmptyElement("read"); attr(out, "path", operation.getAttribute("path"));
          String name = operation.getAttribute("slot");
          attr(out, "slot", name); attr(out, "value", client.readProp(c, c.type.slot(name)).encodeString());
        } else if (command.equals("write")) {
          Slot slot = c.type.slot(operation.getAttribute("slot"));
          if (!slot.isConfig()) throw new IllegalArgumentException(
              "Property is runtime-only; wire a persistent source instead of saving a transient override");
          Value value = slot.def().decodeString(operation.getAttribute("value"));
          slot.assertValue(value);
          client.write(c, slot, value);
        } else if (command.equals("invoke")) {
          Slot slot = c.type.slot(operation.getAttribute("slot"));
          Value value = slot.type.id == Type.voidId ? null :
              Value.defaultForType(slot.type.id).decodeString(operation.getAttribute("value"));
          client.invoke(c, slot, value);
        } else if (command.equals("add")) {
          Type type = schema.type(operation.getAttribute("type"));
          if (type == null || type.isAbstract()) throw new IllegalArgumentException("Unknown/abstract type");
          Slot[] slots = type.configProps();
          Value[] values = new Value[slots.length];
          for (int i = 0; i < slots.length; ++i) values[i] = slots[i].def();
          client.add(c, type, operation.getAttribute("name"), values);
        } else if (command.equals("delete")) {
          client.delete(c);
        } else if (command.equals("rename")) {
          client.rename(c, operation.getAttribute("name"));
        } else if (command.equals("link") || command.equals("unlink")) {
          SoxComponent target = find(client, operation.getAttribute("target"));
          Link link = new Link(c, c.type.slot(operation.getAttribute("slot")), target,
              target.type.slot(operation.getAttribute("target_slot")));
          if (command.equals("link")) client.link(link); else client.unlink(link);
        } else {
          throw new IllegalArgumentException("Unsupported bridge operation: " + command);
        }
      }
      out.writeEndElement(); out.writeEndDocument(); out.flush();
    } finally {
      client.close(); socket.close();
    }
  }
}
