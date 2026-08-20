import streamlit as st
import pandas as pd
import numpy as np
from reportlab.lib.pagesizes import letter, A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
import io
from io import StringIO
from datetime import datetime
import zipfile
import re

# Set page config
st.set_page_config(
    page_title="Haven Cannabis - Pick List Generator",
    page_icon="📦",
    layout="wide"
)

st.title("📦 Sales Order Pick List Generator v1.3")
st.markdown("**Haven Cannabis** | Generate custom pick lists with input package tracking")

# Initialize session state
if 'processed_data' not in st.session_state:
    st.session_state.processed_data = None
# Re-stamped every time data is processed, so anything cached from an earlier upload
# can tell that the data underneath it has been replaced
if 'data_token' not in st.session_state:
    st.session_state.data_token = None
if 'so_data' not in st.session_state:
    st.session_state.so_data = None
if 'assembly_data' not in st.session_state:
    st.session_state.assembly_data = None
if 'product_data' not in st.session_state:
    st.session_state.product_data = None
# Separate-PDF ZIP is kept in session state so the download button survives the
# rerun that clicking it causes (otherwise the button disappears after one click)
if 'separate_pdfs_zip' not in st.session_state:
    st.session_state.separate_pdfs_zip = None
if 'separate_pdfs_zip_name' not in st.session_state:
    st.session_state.separate_pdfs_zip_name = None
if 'separate_pdfs_signature' not in st.session_state:
    st.session_state.separate_pdfs_signature = None

# Function to clean and load CSV data
def load_csv_with_metadata_skip(uploaded_file):
    """
    Load CSV file and skip metadata lines at the top
    """
    try:
        # Read the raw content
        content = uploaded_file.getvalue().decode('utf-8')
        lines = content.split('\n')
        
        # Skip the first 3 lines (metadata) and rejoin
        csv_content = '\n'.join(lines[3:])
        
        # Use StringIO to create a file-like object for pandas
        from io import StringIO
        csv_file = StringIO(csv_content)
        
        # Read with pandas
        df = pd.read_csv(csv_file)
        return df
        
    except Exception as e:
        st.error(f"Error loading CSV: {str(e)}")
        return None

# Function to process the data (replicating your Google Sheets formula)
def process_data(so_df, assembly_df, product_df=None):
    """
    Replicates the Google Sheets QUERY formula logic based on actual CSV structure
    """
    try:
        # Filter sales orders to only include "Processing" status
        if 'Status' in so_df.columns:
            initial_count = len(so_df)
            so_df = so_df[so_df['Status'] == 'Processing'].copy()
            filtered_count = len(so_df)
            st.info(f"Status filter: {filtered_count:,} Processing orders from {initial_count:,} total records")
        else:
            st.warning("No 'Status' column found in Sales Order data - processing all records")
        
        # Extract relevant columns from Sales Orders using actual column names
        so_columns = {
            'Customer': so_df['Customer'],
            'Order_Number': so_df['Order Number'],  # Keep internal name as Order_Number for consistency
            'Category': so_df['Category'],
            'Product': so_df['Product'],
            'Product_ID': so_df['Product Id'],  # Corrected column name
            'Batch_Number': so_df['Package Batch Number'],
            'Lookup_Value': so_df['Package Label'],  # This is what we lookup in Assembly
            'Quantity': so_df['Quantity']
        }
        
        # Add Delivery Date if it exists, converting to "Mon 9/29" format
        if 'Delivery Date' in so_df.columns:
            # Convert to "Mon 9/29" format (3 letter day + M/DD)
            delivery_dates = []
            for date_val in so_df['Delivery Date']:
                if pd.notna(date_val):
                    try:
                        # Convert to datetime and format as "Mon 9/29"
                        if isinstance(date_val, str):
                            dt = pd.to_datetime(date_val)
                        else:
                            dt = pd.to_datetime(date_val)
                        
                        # Format as "Mon 9/29" (3 letter day + M/DD)
                        day_name = dt.strftime('%a')  # 3 letter day name
                        month = str(dt.month)  # Month without leading zero
                        day = str(dt.day)  # Day without leading zero
                        parsed_date = f"{day_name} {month}/{day}"
                        delivery_dates.append(parsed_date)
                    except:
                        delivery_dates.append("")
                else:
                    delivery_dates.append("")
            so_columns['Delivery_Date'] = delivery_dates
        
        # Create base dataframe
        result_df = pd.DataFrame(so_columns)
        
        # Assembly data processing (replicating your VLOOKUP logic)
        # Filter assembly data where Input/Output = "Output"
        assembly_output = assembly_df[assembly_df['Input/Output'] == "Output"]
        assembly_input = assembly_df[assembly_df['Input/Output'] == "Input"]
        
        # Create lookup dictionaries for the nested lookup
        # First lookup: Package Label -> Assembly Number (from Output records)
        package_to_assembly = dict(zip(assembly_output['Package Number'], assembly_output['Assembly Number']))
        
        # Second lookup: Assembly Number -> Package Number (from Input records)  
        assembly_to_input_package = dict(zip(assembly_input['Assembly Number'], assembly_input['Package Number']))
        
        # Perform the nested lookup (replicating your VLOOKUP formula)
        input_package_numbers = []
        for lookup_val in result_df['Lookup_Value']:
            try:
                # First lookup: find Assembly Number from Package Label where Input/Output="Output"
                assembly_number = package_to_assembly.get(lookup_val, None)
                # Second lookup: find Package Number from Assembly Number where Input/Output="Input"
                input_package = assembly_to_input_package.get(assembly_number, "") if assembly_number else ""
                input_package_numbers.append(input_package)
            except:
                input_package_numbers.append("")
        
        result_df['Input_Package_Number'] = input_package_numbers
        
        # Product data processing - calculate number of cases (Quantity ÷ Units Per Case)
        cases = []
        if product_df is not None:
            # Create lookup dictionary: Product ID -> Units Per Case
            product_lookup = dict(zip(product_df['ID'], product_df['Units Per Case']))
            
            for idx, row in result_df.iterrows():
                product_id = row['Product_ID']
                quantity = row['Quantity']
                
                try:
                    units_per_case = product_lookup.get(product_id, None)
                    
                    # Calculate cases if we have valid data
                    if (pd.notna(units_per_case) and units_per_case != '' and 
                        pd.notna(quantity) and quantity != '' and 
                        float(units_per_case) > 0):
                        
                        calculated_cases = float(quantity) / float(units_per_case)
                        # Round to 2 decimal places for storage
                        cases.append(round(calculated_cases, 2))
                    else:
                        cases.append(None)  # Use None instead of empty string
                except:
                    cases.append(None)  # Use None instead of empty string
        else:
            # No product data available
            cases = [None] * len(result_df)  # Use None instead of empty string
        
        result_df['Cases'] = cases
        
        # Remove the Lookup_Value and Product_ID columns as they're not needed in the final output
        result_df = result_df.drop(['Lookup_Value', 'Product_ID'], axis=1)
        
        # Reorder columns
        base_columns = ['Customer', 'Order_Number', 'Category', 'Product', 'Batch_Number', 'Input_Package_Number', 'Quantity', 'Cases']
        if 'Delivery_Date' in result_df.columns:
            columns_order = base_columns + ['Delivery_Date']
        else:
            columns_order = base_columns
        
        result_df = result_df[columns_order]
        
        # Filter out null customers and sort by Product A-Z (default sort)
        result_df = result_df[result_df['Customer'].notna() & (result_df['Customer'] != "")]
        result_df = result_df.sort_values(['Product', 'Customer', 'Order_Number', 'Category'])  # Product first for A-Z sort
        
        # Reset index
        result_df = result_df.reset_index(drop=True)
        
        return result_df
        
    except Exception as e:
        st.error(f"Error processing data: {str(e)}")
        st.info("Please check that your CSV files have the expected column structure.")
        st.info(f"Available Sales Order columns: {list(so_df.columns)}")
        st.info(f"Available Assembly columns: {list(assembly_df.columns)}")
        if product_df is not None:
            st.info(f"Available Product columns: {list(product_df.columns)}")
        st.info("Note: 'Delivery Date' column is optional in Sales Order CSV")
        return None

# Helper functions for PDF generation
def wrap_text_smart(text, column_width_inches, font_size=8):
    """Smart text wrapping based on actual column width"""
    if not text or pd.isna(text):
        return ""
    
    text = str(text).strip()
    if not text:
        return ""
    
    # More accurate character estimation for Helvetica font
    # Average character width in Helvetica is roughly 0.5-0.6 * font_size
    points_width = column_width_inches * 72 - 12  # Subtract padding (6 points each side)
    avg_char_width = 0.55 * font_size  # More conservative estimate
    max_chars_per_line = int(points_width / avg_char_width)
    
    # Don't wrap if text fits comfortably
    if len(text) <= max_chars_per_line:
        return text
    
    # Find the best break point after a hyphen
    best_break = None
    
    # Look for hyphens within reasonable range, break AFTER the hyphen
    for i in range(max_chars_per_line, max(max_chars_per_line//3, 5), -1):
        if i < len(text) and text[i-1] == '-':
            best_break = i  # This puts hyphen at end of first line
            break
    
    # If no hyphen found, look for spaces
    if not best_break:
        for i in range(max_chars_per_line, max(max_chars_per_line//3, 5), -1):
            if i < len(text) and text[i-1] == ' ':
                best_break = i - 1  # Break before the space
                break
    
    # If still no good break point, don't wrap (let it overflow slightly rather than bad break)
    if not best_break or best_break < max_chars_per_line//3:
        return text
    
    return text[:best_break] + '\n' + text[best_break:].strip()

def wrap_text(text, max_length=20, break_chars=None):
    """Simple text wrapping function for columns with known limits"""
    if not text or len(str(text)) <= max_length:
        return str(text)
    
    text = str(text)
    
    # Find break points, prioritizing hyphens
    for i in range(max_length, max(max_length//2, 1), -1):
        if i < len(text):
            if text[i-1] == '-':
                return text[:i] + '\n' + text[i:].strip()
            elif text[i-1] == ' ':
                return text[:i-1] + '\n' + text[i:].strip()
    
    # No good break point found, break at max_length
    return text[:max_length] + '\n' + text[max_length:]

def truncate_package_number(package_text):
    """Get last 14 characters of package number"""
    if not package_text or len(str(package_text)) <= 14:
        return str(package_text)
    return str(package_text)[-14:]

def format_number_smart(value):
    """
    Format a number smartly - remove unnecessary decimals
    1.0 -> "1", 1.5 -> "1.5", None -> ""
    """
    if value is None or pd.isna(value):
        return ""
    
    try:
        num = float(value)
        # Check if it's a whole number
        if num == int(num):
            return str(int(num))
        else:
            # Round to 2 decimal places, remove trailing zeros
            formatted = f"{num:.2f}".rstrip('0').rstrip('.')
            return formatted
    except (ValueError, TypeError):
        return str(value)

def is_partial_case(cases_value):
    """
    Check if cases value represents a partial case (has decimal component)
    Returns True if there's a decimal portion > 0
    """
    if cases_value is None or pd.isna(cases_value):
        return False
    
    try:
        num = float(cases_value)
        # Check if there's a fractional part
        return num != int(num)
    except (ValueError, TypeError):
        return False

def add_page_footer(canvas, doc, page_size, unique_customers, unique_sales_orders, unique_delivery_dates):
    """Add footer with page numbers, generation info, customer/SO/delivery date info on all pages"""
    canvas.saveState()
    
    page_width = page_size[0]
    page_num = canvas.getPageNumber()
    
    # Page number and generation time
    page_text = f"Page {page_num}"
    gen_time = datetime.now().strftime('%m/%d/%Y %I:%M %p')
    gen_text = f"Generated: {gen_time}"
    
    canvas.setFont('Helvetica', 8)
    canvas.setFillColor(colors.Color(0.4, 0.4, 0.4))
    
    # Left side - generation time
    canvas.drawString(0.3*inch, 0.3*inch, gen_text)
    # Right side - page number  
    canvas.drawRightString(page_width - 0.3*inch, 0.3*inch, page_text)
    
    # Center - Customer, SO, and Delivery Date info (on all pages, no labels)
    center_info_parts = []
    
    # Add customer info (always show if customers exist)
    if unique_customers:
        if len(unique_customers) <= 3:
            customer_text = ", ".join(unique_customers)
        else:
            customer_text = f"{', '.join(unique_customers[:2])} + {len(unique_customers)-2} more"
        center_info_parts.append(customer_text)
    
    # Add SO info (always show if sales orders exist)
    if unique_sales_orders:
        if len(unique_sales_orders) <= 5:
            so_text = ", ".join(unique_sales_orders)
        else:
            so_text = f"{', '.join(unique_sales_orders[:3])} + {len(unique_sales_orders)-3} more"
        center_info_parts.append(so_text)
    
    # Add delivery date info with "Delivery:" prefix
    if unique_delivery_dates:
        if len(unique_delivery_dates) <= 3:
            delivery_text = f"Delivery: {', '.join(unique_delivery_dates)}"
        else:
            delivery_text = f"Delivery: {', '.join(unique_delivery_dates[:2])} + {len(unique_delivery_dates)-2} more"
        center_info_parts.append(delivery_text)
    
    # Display center info if we have any
    if center_info_parts:
        center_text = " | ".join(center_info_parts)
        # Calculate center position
        text_width = canvas.stringWidth(center_text, 'Helvetica', 8)
        x_position = (page_width - text_width) / 2
        canvas.drawString(x_position, 0.3*inch, center_text)
    
    canvas.restoreState()

# Function to generate PDF
def generate_document_title(unique_customers, unique_sales_orders):
    """Generate document title and filename based on customers and sales orders"""
    if len(unique_customers) == 1 and len(unique_sales_orders) == 1:
        return f"Pick List {unique_customers[0]} {unique_sales_orders[0]}"
    elif len(unique_customers) == 1:
        if len(unique_sales_orders) <= 3:
            return f"Pick List {unique_customers[0]} {' '.join(unique_sales_orders)}"
        else:
            return f"Pick List {unique_customers[0]} Multi-SO"
    elif len(unique_sales_orders) == 1:
        if len(unique_customers) <= 2:
            return f"Pick List {' '.join(unique_customers)} {unique_sales_orders[0]}"
        else:
            return f"Pick List Multi-Customer {unique_sales_orders[0]}"
    else:
        return "Pick List Multi-Customer Multi-SO"

def generate_pdf(df, selected_filters=None, hide_customer=False, hide_sales_order=False, portrait_mode=False):
    """
    Generate a styled PDF report with landscape or portrait orientation and custom color scheme
    v1.2: Combined Qty/Cases column with partial case highlighting
    """
    # Create document title and file name based on data
    unique_customers = sorted(df['Customer'].unique())
    unique_sales_orders = sorted(df['Order_Number'].unique())
    doc_title = generate_document_title(unique_customers, unique_sales_orders)
    
    buffer = io.BytesIO()
    
    # Choose orientation based on user preference
    from reportlab.lib.pagesizes import A4, landscape
    if portrait_mode:
        page_size = A4
        doc = SimpleDocTemplate(buffer, pagesize=A4, 
                              title=doc_title,  # Set PDF document title
                              topMargin=0.5*inch, bottomMargin=0.5*inch,
                              leftMargin=0.3*inch, rightMargin=0.3*inch)
    else:
        page_size = landscape(A4)
        doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), 
                              title=doc_title,  # Set PDF document title
                              topMargin=0.5*inch, bottomMargin=0.5*inch,
                              leftMargin=0.3*inch, rightMargin=0.3*inch)
    
    # Get styles
    styles = getSampleStyleSheet()
    filter_style = ParagraphStyle(
        'FilterStyle',
        parent=styles['Normal'],
        fontSize=9,
        textColor=colors.Color(0.4, 0.4, 0.4),
        alignment=1,  # Center alignment
        spaceAfter=10
    )
    
    # Custom style for combined Qty/Cases cell with tight line spacing
    qty_combined_style = ParagraphStyle(
        'QtyCombinedStyle',
        parent=styles['Normal'],
        fontSize=10,
        alignment=1,  # Center
        leading=13,   # Tighter line spacing (default is ~12 for size 10)
        spaceBefore=0,
        spaceAfter=0
    )
    
    elements = []
    
    # Add filter information in header if any
    if selected_filters:
        filter_values = []
        for key, value in selected_filters.items():
            if value:
                # Just show the values, not the labels
                if isinstance(value, list):
                    filter_values.extend(value)
                else:
                    filter_values.append(value)
        
        if filter_values:
            filter_text = " | ".join(filter_values)
            filter_para = Paragraph(filter_text, filter_style)
            elements.append(filter_para)
    
    # Extract unique delivery dates if the column exists
    unique_delivery_dates = []
    if 'Delivery_Date' in df.columns:
        delivery_dates = df['Delivery_Date'].dropna()
        delivery_dates = delivery_dates[delivery_dates != ""]  # Remove empty strings
        if len(delivery_dates) > 0:
            unique_delivery_dates = sorted(delivery_dates.unique())
    
    # Build headers and column widths based on visibility options and orientation
    # NOTE: Combined Qty and Cases into single "Qty/Cases" column
    headers = []
    col_widths = []
    
    if not hide_customer:
        headers.append('Customer')
        col_widths.append(1.3*inch if not portrait_mode else 1*inch)
    
    if not hide_sales_order:
        headers.append('SO')
        col_widths.append(1*inch if not portrait_mode else 0.8*inch)
    
    # Always include these columns - Note: Combined Qty/Cases column
    headers.extend(['Category', 'Product', 'Batch', 'Package', 'Qty/Cases'])
    
    # Adjust column widths based on hidden columns and orientation
    # Qty/Cases column needs to be wider to fit the combined content
    if portrait_mode:
        # Portrait mode - tighter spacing
        if hide_customer and hide_sales_order:
            col_widths.extend([0.8*inch, 3.0*inch, 1*inch, 1*inch, 1.0*inch])
        elif hide_customer or hide_sales_order:
            col_widths.extend([0.7*inch, 2.6*inch, 0.9*inch, 0.9*inch, 1.0*inch])
        else:
            col_widths.extend([0.6*inch, 2.3*inch, 0.8*inch, 0.8*inch, 0.9*inch])
    else:
        # Landscape mode
        if hide_customer and hide_sales_order:
            col_widths.extend([1.2*inch, 4.6*inch, 1.4*inch, 1.4*inch, 1.2*inch])
        elif hide_customer or hide_sales_order:
            col_widths.extend([1.1*inch, 4.0*inch, 1.3*inch, 1.3*inch, 1.1*inch])
        else:
            col_widths.extend([1*inch, 3.3*inch, 1.2*inch, 1.2*inch, 1.0*inch])
    
    # Prepare table data
    table_data = [headers]
    
    # Track which rows are partial cases (for highlighting)
    partial_case_rows = []  # Will store row indices (1-based, since 0 is header)
    
    for row_idx, (_, row) in enumerate(df.iterrows()):
        # Handle None/NaN values for batch number
        batch_number = str(row['Batch_Number']) if pd.notna(row['Batch_Number']) and str(row['Batch_Number']).lower() != 'none' else ""
        
        # Determine product column width based on visibility settings and orientation
        if portrait_mode:
            if hide_customer and hide_sales_order:
                product_width = 3.0  # Both hidden
            elif hide_customer or hide_sales_order:
                product_width = 2.6  # One hidden
            else:
                product_width = 2.3  # None hidden
        else:
            if hide_customer and hide_sales_order:
                product_width = 4.6  # Both hidden
            elif hide_customer or hide_sales_order:
                product_width = 4.0  # One hidden
            else:
                product_width = 3.3  # None hidden
        
        # Process text fields with smart wrapping for product names
        product_name = wrap_text_smart(str(row['Product']), product_width, font_size=8)
        category_wrapped = wrap_text(str(row['Category']), 12)
        batch_display = wrap_text(batch_number, 15) if batch_number else ""
        package_display = truncate_package_number(row['Input_Package_Number']) if pd.notna(row['Input_Package_Number']) else ""
        
        # Format Quantity and Cases with smart decimal handling
        qty_formatted = format_number_smart(row['Quantity'])
        cases_formatted = format_number_smart(row['Cases'])
        
        # Check if this is a partial case
        is_partial = is_partial_case(row['Cases'])
        
        # Determine singular vs plural for Units and Cases
        try:
            qty_num = float(row['Quantity']) if pd.notna(row['Quantity']) else 0
            unit_label = "Unit" if qty_num == 1 else "Units"
        except:
            unit_label = "Units"
        
        try:
            cases_num = float(row['Cases']) if pd.notna(row['Cases']) else 0
            case_label = "Case" if cases_num == 1 else "Cases"
        except:
            case_label = "Cases"
        
        # Build combined Qty/Cases cell content
        # Units line: "X Units" - prominent, bold
        # Cases line: "Y Cases" - slightly smaller, centered below, tighter spacing
        if cases_formatted and cases_formatted != "":
            if is_partial:
                # Mark as partial case row for highlighting
                partial_case_rows.append(row_idx + 1)  # +1 because row 0 is header
                # Build combined text with PARTIAL indicator - tighter spacing with smaller line break
                qty_cases_text = f"<b><font size='10'>{qty_formatted} {unit_label}</font></b><br/><font size='8' color='#991111'><b>{cases_formatted} {case_label} (PARTIAL)</b></font>"
            else:
                # Normal case - just show units and cases with tighter spacing
                qty_cases_text = f"<b><font size='10'>{qty_formatted} {unit_label}</font></b><br/><font size='8' color='#555555'>{cases_formatted} {case_label}</font>"
        else:
            # No cases data - just show units
            qty_cases_text = f"<b><font size='10'>{qty_formatted} {unit_label}</font></b>"
        
        # Create Paragraph for the combined Qty/Cases cell with tight spacing
        qty_cases_para = Paragraph(qty_cases_text, qty_combined_style)
        
        # Build row data based on visibility options
        row_data = []
        
        if not hide_customer:
            row_data.append(str(row['Customer']))
        
        if not hide_sales_order:
            row_data.append(str(row['Order_Number']))
        
        # Always include these columns
        row_data.extend([
            category_wrapped,
            product_name,
            batch_display,
            package_display,
            qty_cases_para  # Combined Qty/Cases as Paragraph
        ])
        
        table_data.append(row_data)
    
    # Create table with header repetition
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    
    # Haven Cannabis brand color scheme
    haven_teal = colors.Color(61/255, 192/255, 204/255)        # #3DC0CC - Haven primary teal
    haven_gold = colors.Color(255/255, 202/255, 69/255)        # #FFCA45 - Haven gold accent  
    haven_purple = colors.Color(146/255, 39/255, 143/255)      # Haven purple (estimated)
    alt_row_color = colors.Color(248/255, 252/255, 253/255)    # Very light teal
    border_color = colors.Color(0.6, 0.6, 0.6)                 # Neutral gray for borders
    
    # Partial case highlight color - light orange/amber to stand out
    partial_case_color = colors.Color(255/255, 243/255, 224/255)  # Light amber/orange #FFF3E0
    
    # Create base table styles with Haven branding and proper vertical alignment
    table_style = [
        # Header row - Haven teal branding
        ('BACKGROUND', (0, 0), (-1, 0), haven_teal),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),          # Horizontal center
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),         # Vertical center for ALL cells
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 15),
        ('TOPPADDING', (0, 0), (-1, 0), 15),
        
        # Data rows with increased padding for better vertical centering
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, border_color),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 1), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 10),
    ]
    
    # Apply alternating row colors for non-partial rows
    # We need to manually set backgrounds because partial rows override the alternating pattern
    for row_num in range(1, len(table_data)):
        if row_num in partial_case_rows:
            # Partial case row - use amber highlight
            table_style.append(('BACKGROUND', (0, row_num), (-1, row_num), partial_case_color))
        else:
            # Normal row - use alternating white/light teal
            if (row_num - 1) % 2 == 0:  # Even data rows (0-indexed from data, not header)
                table_style.append(('BACKGROUND', (0, row_num), (-1, row_num), colors.white))
            else:
                table_style.append(('BACKGROUND', (0, row_num), (-1, row_num), alt_row_color))
    
    table.setStyle(TableStyle(table_style))
    elements.append(table)
    
    # Create footer callback with closure to pass variables
    def footer_callback(canvas, doc):
        return add_page_footer(canvas, doc, page_size, unique_customers, unique_sales_orders, unique_delivery_dates)
    
    # Build PDF with footer
    doc.build(elements, onFirstPage=footer_callback, onLaterPages=footer_callback)
    buffer.seek(0)
    return buffer

# Icon for the Generate Separate PDFs button, embedded as a base64 data URI so the
# app stays a single file with no image asset to deploy. Streamlit scales an image
# in a button label down to the height of the button text (about 16 pixels), so it
# is stored here at 48px to stay sharp on high-resolution screens.
# Artwork from Flaticon - credited in the "How it Works" panel on the welcome screen.
SEPARATE_PDFS_ICON = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAMAAABg3Am1AAAAwFBMVEUAAAD19/n+4HwCAgD92nAYFQ3/6IJmaW4WFgmtjUTS2+nh5e4uMTVeYWU9PkEtIw/7zmMAAAD+94uYfDtpWS2umVX///9HSk8qIg4BAABGOhqah0t0YzINCQQAAABVRyXJqVeegT4BAQCZnaMXFQokHAm6pFvWvGllYVIHBgX/+XomKC92WCVvc3kpHg3cwWyNfUVHPiM9Qkt7fYOqqqrMzMzMmWZdY2lURB6AaDKutsB+gYc/Pz+ggz52fYQAAABCjll/AAAAQHRSTlMA/v75/v7+/iH+/v////8V/tT+/v7/Av7/jP7//jOp//7/cf4e/////07+/wj/GP//////AwUFUv/8/P8E/UkAZxVDUgAAAf5JREFUeNrNlmt3ojAQQEkmQEFtBbMEKK8taKmvdtvu+/H/f9ZOUkD07CZ87D1+UJzLTDJx0LLeLfvmaswx0ofnBVwQJI0mPoE48z6ckdnwMHz/+noefwff2TZ0zghZCQ/R50hxWQ9klD3FFzXZNtbV8fVPENydhGLN8HbP7jmL09uD7x8EFL+6+C8BpyuoiQbfJ6SGPscNrGh8jRf1EBEMwkcKLZkRLTPiBtFJiJ9rMdcifohiVFKJuyKuNQjcs74xUsj0i5b8hL6VqqQ5mRkgu5RDMyzaJUYWNrOTXlgL/2Wh5cUXccjVRsk1fFNnQQcGlOEt3AyLdk19cKEdCenOvIZdOgjTFu3CSFi3ZqFdj0uam4V5OhK4bRZsPhJWMDPFz1SYFI7gbSvwTYIP1daDo8qQZiWIg1uT2v0/AsosVRkK2eQYm9mGqa7XMgQKOZN+M0SOFupooIxS6kFiAafLJXPwE1PX/k0nhRwsWDEUqA680+M98shwY7sMesG5fxtumzADK0iNGVDZbCp8MedTYCU494wCdcIyjrnD4gQncYWCMQV94vzWWeL4y6VgToE5cL5XkMujNElQzZKnLwrM29Q7YSanQJHKNUwxcJPkuExsLGkpHTNqMOV40CdFM/w95G+PRO5NgkPSPRQDmMTpObdv8isjebN/p39K/gIDJjm2Rka6lwAAAABJRU5ErkJggg=="

# Helper functions for generating one PDF per Sales Order (v1.3)
def sanitize_filename(name):
    """
    Make a string safe to use as a file name inside a ZIP on Windows.
    Customer names end up in these names, so replace the characters Windows
    forbids ( \\ / : * ? " < > | ) with a space, collapse the extra spaces, and
    trim trailing periods/spaces - Explorer can't open entries that end in those.
    """
    cleaned = re.sub(r'[\\/:*?"<>|]', ' ', str(name))
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    cleaned = cleaned.rstrip('. ')

    # Fall back to something valid if the name was nothing but bad characters
    return cleaned if cleaned else "Pick List"

def make_unique_filename(filename, used_filenames):
    """
    Guarantee a unique entry name inside the ZIP. Duplicate names in a ZIP are
    silently lossy, so collisions get " (2)", " (3)", etc. added before the .pdf.
    Adds the returned name to used_filenames.
    """
    if filename not in used_filenames:
        used_filenames.add(filename)
        return filename

    # Split the extension off so the counter goes before it: "name (2).pdf"
    if filename.lower().endswith('.pdf'):
        base = filename[:-4]
        extension = '.pdf'
    else:
        base = filename
        extension = ''

    counter = 2
    while f"{base} ({counter}){extension}" in used_filenames:
        counter += 1

    unique_filename = f"{base} ({counter}){extension}"
    used_filenames.add(unique_filename)
    return unique_filename

def generate_separate_pdfs_zip(df, selected_filters=None, hide_customer=False, hide_sales_order=False,
                               portrait_mode=False, progress_bar=None):
    """
    Build one PDF per Sales Order in df and return them all as a single in-memory ZIP.
    Each PDF comes from the existing generate_pdf() called on that Sales Order's rows,
    so every file is identical to what the app produces for that SO on its own.
    """
    sales_orders = sorted(df['Order_Number'].unique())
    used_filenames = set()
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for index, sales_order in enumerate(sales_orders):
            # One Sales Order's rows out of the already-filtered data
            so_df = df[df['Order_Number'] == sales_order]
            so_customers = sorted(so_df['Customer'].unique())

            # The line printed across the top of the PDF comes from selected_filters.
            # Handing over the whole filter would print every selected store on every
            # sheet ("Haven Belmont | Haven DTLB | Haven Paramount"), which the pickers
            # read before they get to the store name in the footer. Narrow it to the
            # store and order this particular sheet covers.
            so_filters = None
            if selected_filters:
                so_filters = dict(selected_filters)  # copy - leave the caller's filters alone
                if 'Customers' in so_filters:
                    so_filters['Customers'] = so_customers
                if 'Sales Orders' in so_filters:
                    so_filters['Sales Orders'] = [str(sales_order)]

            pdf_buffer = generate_pdf(so_df, so_filters, hide_customer, hide_sales_order, portrait_mode)

            # generate_document_title() returns "Pick List {Customer} {SO}" when handed
            # a single customer and a single order - exactly the name the pickers want
            document_title = generate_document_title(so_customers, [sales_order])
            filename = make_unique_filename(sanitize_filename(document_title) + ".pdf", used_filenames)

            zip_file.writestr(filename, pdf_buffer.getvalue())

            if progress_bar is not None:
                progress_bar.progress(
                    (index + 1) / len(sales_orders),
                    text=f"Generating PDF {index + 1} of {len(sales_orders)}..."
                )

    zip_buffer.seek(0)
    return zip_buffer

# Sidebar for file uploads
st.sidebar.header("📊 Data Sources")

# Sales Order Item History CSV Upload
st.sidebar.subheader("📋 Sales Orders")
so_file = st.sidebar.file_uploader(
    "Processing orders from last 30 days",
    type=['csv'],
    key="so_upload"
)

# Assembly Data CSV Upload  
st.sidebar.subheader("🔧 Assembly Data")
assembly_file = st.sidebar.file_uploader(
    "Assembly data from last 3 days",
    type=['csv'],
    key="assembly_upload"
)

# Product List CSV Upload
st.sidebar.subheader("📦 Product List")
product_file = st.sidebar.file_uploader(
    "Product catalog with case quantities",
    type=['csv'],
    key="product_upload"
)

# Process button
if st.sidebar.button("🚀 Process Data", type="primary", disabled=not (so_file and assembly_file)):
    with st.spinner("Processing your data..."):
        try:
            # Load the data using our custom function that skips metadata
            so_df = load_csv_with_metadata_skip(so_file)
            assembly_df = load_csv_with_metadata_skip(assembly_file)
            
            # Load product data if available (no metadata skip needed for this one)
            product_df = None
            if product_file:
                try:
                    product_df = pd.read_csv(product_file)
                    st.session_state.product_data = product_df
                    st.info(f"Product List: {len(product_df):,} products loaded")
                except Exception as e:
                    st.warning(f"Could not load Product List: {str(e)}. Continuing without case quantities.")
            
            if so_df is None or assembly_df is None:
                st.error("❌ Failed to load required CSV files. Please check your file formats.")
                st.stop()
            
            st.session_state.so_data = so_df
            st.session_state.assembly_data = assembly_df
            
            file_info = f"Sales Orders: {len(so_df):,} rows | Assembly Data: {len(assembly_df):,} rows"
            if product_df is not None:
                file_info += f" | Products: {len(product_df):,} rows"
            
            st.success(f"✅ Files loaded successfully!")
            st.info(file_info)
            
            # Process the data
            processed_df = process_data(so_df, assembly_df, product_df)
            
            if processed_df is not None:
                st.session_state.processed_data = processed_df
                # New data makes anything generated from the old data stale
                st.session_state.data_token = datetime.now().isoformat()
                st.success(f"✅ Successfully processed {len(processed_df):,} records")
            else:
                st.error("❌ Failed to process data. Please check your CSV file structure.")
                
        except Exception as e:
            st.error(f"❌ Error processing files: {str(e)}")

# Main content area
if st.session_state.processed_data is not None:
    processed_df = st.session_state.processed_data
    
    # Create tabs for better organization
    tab1, tab2 = st.tabs(["🎯 Pick List Generator", "📊 Data Overview"])
    
    with tab1:
        st.header("🎯 Create Custom Pick List")
        
        # Filter section
        col1, col2, col3 = st.columns([2, 2, 2])
        
        with col1:
            customers = sorted(processed_df['Customer'].unique().tolist())
            selected_customers = st.multiselect("Select Customers", customers)
            
        with col2:
            if selected_customers:
                filtered_orders = processed_df[processed_df['Customer'].isin(selected_customers)]['Order_Number'].unique()
            else:
                filtered_orders = processed_df['Order_Number'].unique()
            orders = sorted(filtered_orders.tolist())
            selected_orders = st.multiselect("Select Sales Orders", orders)
            
        with col3:
            if selected_customers:
                filtered_categories = processed_df[processed_df['Customer'].isin(selected_customers)]['Category'].unique()
            elif selected_orders:
                filtered_categories = processed_df[processed_df['Order_Number'].isin(selected_orders)]['Category'].unique()
            else:
                filtered_categories = processed_df['Category'].unique()
            categories = sorted(filtered_categories.tolist())
            selected_categories = st.multiselect("Select Categories", categories)
        
        # PDF Options and Generate Buttons
        col1, col2, col3, col4, col5 = st.columns([2, 2, 2, 2, 2])
        
        with col1:
            show_customer = st.checkbox("Show Customer Column", value=False, help="Include Customer column in PDF report")
        
        with col2:
            show_sales_order = st.checkbox("Show SO Column", value=False, help="Include Sales Order column in PDF report")
        
        with col3:
            landscape_mode = st.checkbox("Landscape Mode", value=False, help="Generate PDF in landscape orientation instead of portrait")
        
        with col4:
            generate_pdf_btn = st.button("📑 Generate PDF", type="primary")
        
        with col5:
            # One PDF per Sales Order, delivered as a single ZIP
            generate_separate_pdfs_btn = st.button(f"![]({SEPARATE_PDFS_ICON}) Generate Separate PDFs",
                                                   help="Create one PDF per Sales Order and download them all as a ZIP")

        # Apply filters
        filtered_df = processed_df.copy()
        
        applied_filters = {}
        
        if selected_customers:
            filtered_df = filtered_df[filtered_df['Customer'].isin(selected_customers)]
            applied_filters['Customers'] = selected_customers
            
        if selected_orders:
            filtered_df = filtered_df[filtered_df['Order_Number'].isin(selected_orders)]
            applied_filters['Sales Orders'] = selected_orders
            
        if selected_categories:
            filtered_df = filtered_df[filtered_df['Category'].isin(selected_categories)]
            applied_filters['Categories'] = selected_categories
        
        # Show partial case indicator in the results preview
        partial_count = filtered_df['Cases'].apply(is_partial_case).sum()
        
        # Show filtered results
        st.subheader(f"📋 Pick List Results ({len(filtered_df):,} records)")
        
        if partial_count > 0:
            st.warning(f"⚠️ **{partial_count} partial case(s)** detected - these will be highlighted in the PDF report")
        
        st.dataframe(filtered_df, use_container_width=True)
        
        # Download section
        col1, col2 = st.columns(2)
        
        with col1:
            # CSV download
            csv = filtered_df.to_csv(index=False)
            st.download_button(
                label="📄 Download CSV",
                data=csv,
                file_name=f"pick_list_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
                use_container_width=True
            )
        
        with col2:
            # PDF download (triggered by the button above)
            if generate_pdf_btn:
                with st.spinner("Generating PDF report..."):
                    # Invert the logic - pass hide flags to the PDF function
                    hide_customer = not show_customer
                    hide_sales_order = not show_sales_order
                    portrait_mode = not landscape_mode
                    
                    pdf_buffer = generate_pdf(filtered_df, applied_filters, hide_customer, hide_sales_order, portrait_mode)
                    
                # Generate dynamic filename based on data
                unique_customers = sorted(filtered_df['Customer'].unique())
                unique_sales_orders = sorted(filtered_df['Order_Number'].unique())
                filename = generate_document_title(unique_customers, unique_sales_orders) + ".pdf"
                
                # Immediately trigger download
                st.download_button(
                    label="📑 Download PDF Report",
                    data=pdf_buffer,
                    file_name=filename,
                    mime="application/pdf",
                    use_container_width=True,
                    key="pdf_download"
                )
                st.success("✅ PDF report generated successfully!")
            else:
                # Show placeholder when PDF not generated
                st.button("📑 Download PDF Report", disabled=True, help="Click 'Generate PDF' button above first", use_container_width=True)

        # Separate PDFs section - one PDF per Sales Order, zipped together
        # The data, filters and options are all recorded alongside the ZIP. If any of
        # them change, the stored ZIP is dropped so we never quietly hand out stale
        # pick lists. The data token covers the case where the same filters are
        # re-applied after a fresh upload, which would otherwise look unchanged.
        separate_pdfs_signature = f"{st.session_state.data_token}|{applied_filters}|{show_customer}|{show_sales_order}|{landscape_mode}"

        if st.session_state.separate_pdfs_signature != separate_pdfs_signature:
            st.session_state.separate_pdfs_zip = None
            st.session_state.separate_pdfs_zip_name = None

        if generate_separate_pdfs_btn:
            if len(filtered_df) == 0:
                st.warning("⚠️ No records match the current filters - nothing to generate.")
            else:
                sales_orders = sorted(filtered_df['Order_Number'].unique())

                # Tell the user how much work this is before starting - with no filters
                # applied this can easily be 100+ orders
                st.info(f"📦 This will create {len(sales_orders)} PDF(s) - one per Sales Order.")

                # Only bother with a progress bar for big batches; small ones finish immediately
                progress_bar = st.progress(0.0, text="Generating PDFs...") if len(sales_orders) > 20 else None

                with st.spinner(f"Generating {len(sales_orders)} PDF(s)..."):
                    # Same inverted logic the single-PDF button uses above
                    hide_customer = not show_customer
                    hide_sales_order = not show_sales_order
                    portrait_mode = not landscape_mode

                    zip_buffer = generate_separate_pdfs_zip(filtered_df, applied_filters, hide_customer,
                                                            hide_sales_order, portrait_mode, progress_bar)

                if progress_bar is not None:
                    progress_bar.empty()

                # Include the store name in the ZIP name when it's a single customer
                unique_customers = sorted(filtered_df['Customer'].unique())
                today = datetime.now().strftime('%Y-%m-%d')
                if len(unique_customers) == 1:
                    zip_filename = f"Pick Lists {sanitize_filename(unique_customers[0])} {today}.zip"
                else:
                    zip_filename = f"Pick Lists {today}.zip"

                # Store the result so the download button below survives the rerun
                st.session_state.separate_pdfs_zip = zip_buffer.getvalue()
                st.session_state.separate_pdfs_zip_name = zip_filename
                st.session_state.separate_pdfs_signature = separate_pdfs_signature

        # Rendered from session state, so it stays on screen after a download and
        # can be clicked again without regenerating everything
        if st.session_state.separate_pdfs_zip is not None:
            st.download_button(
                label=f"![]({SEPARATE_PDFS_ICON}) Download {st.session_state.separate_pdfs_zip_name}",
                data=st.session_state.separate_pdfs_zip,
                file_name=st.session_state.separate_pdfs_zip_name,
                mime="application/zip",
                use_container_width=True,
                key="separate_pdfs_download"
            )
            st.success("✅ Separate PDFs generated successfully!")
    
    with tab2:
        st.header("📊 Data Overview")
        
        # Summary metrics
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("🛒 Total Sales Orders", len(processed_df['Order_Number'].unique()))
        with col2:
            st.metric("👥 Unique Customers", len(processed_df['Customer'].unique()))
        with col3:
            st.metric("📦 Total Items", len(processed_df))
        with col4:
            st.metric("🏷️ Categories", len(processed_df['Category'].unique()))
        with col5:
            # Show partial cases count
            partial_total = processed_df['Cases'].apply(is_partial_case).sum()
            st.metric("⚠️ Partial Cases", partial_total)
        
        # Show breakdown by category
        st.subheader("📈 Category Breakdown")
        category_counts = processed_df['Category'].value_counts()
        st.bar_chart(category_counts)
        
        # Show breakdown by customer
        st.subheader("👥 Customer Breakdown")
        customer_counts = processed_df['Customer'].value_counts().head(10)
        st.bar_chart(customer_counts)
        
        # Show case analysis if available
        if 'Cases' in processed_df.columns and processed_df['Cases'].notna().sum() > 0:
            st.subheader("📦 Cases Analysis")
            col1, col2 = st.columns(2)
            
            with col1:
                # Items with calculated cases
                items_with_cases = processed_df[processed_df['Cases'].notna() & (processed_df['Cases'] != "")]
                st.write(f"**Items with Cases Calculated:** {len(items_with_cases):,} of {len(processed_df):,}")
                
                if len(items_with_cases) > 0:
                    # Convert to numeric for analysis
                    cases_numeric = pd.to_numeric(items_with_cases['Cases'], errors='coerce')
                    cases_numeric = cases_numeric.dropna()
                    
                    if len(cases_numeric) > 0:
                        st.write(f"**Average Cases per Line:** {cases_numeric.mean():.2f}")
                        st.write(f"**Total Cases:** {cases_numeric.sum():.2f}")
                        st.write(f"**Largest Line:** {cases_numeric.max():.2f} cases")
                        
                        # Partial cases breakdown
                        partial_cases = cases_numeric[cases_numeric != cases_numeric.astype(int)]
                        full_cases = cases_numeric[cases_numeric == cases_numeric.astype(int)]
                        st.write(f"**Full Cases:** {len(full_cases):,} lines")
                        st.write(f"**Partial Cases:** {len(partial_cases):,} lines")
            
            with col2:
                # Cases distribution
                if len(items_with_cases) > 0:
                    # Group cases into ranges for better visualization
                    cases_numeric = pd.to_numeric(items_with_cases['Cases'], errors='coerce').dropna()
                    if len(cases_numeric) > 0:
                        # Create ranges
                        cases_ranges = pd.cut(cases_numeric, bins=[0, 0.5, 1, 2, 5, 10, float('inf')], 
                                            labels=['< 0.5', '0.5-1', '1-2', '2-5', '5-10', '10+'])
                        cases_range_counts = cases_ranges.value_counts().sort_index()
                        st.write("**Cases Distribution:**")
                        st.bar_chart(cases_range_counts)
        
        # Show raw data with search
        st.subheader("🔍 Full Dataset")
        st.dataframe(processed_df, use_container_width=True)

else:
    # Welcome screen when no data is loaded
    if not so_file and not assembly_file:
        st.info("👈 Upload the required CSV files in the sidebar to get started")
        
        # Show helpful information
        with st.expander("ℹ️ How it Works", expanded=True):
            st.markdown("""
            **📋 Upload** → **🔄 Process** → **🎯 Filter** → **📥 Download**
            
            **Haven Cannabis Pick List Generator v1.3** processes your sales order, assembly, and product data to create custom pick lists with input package tracking and calculated case requirements.
            
            **Key Features:**
            - 🔗 Links Package Labels to Assembly Numbers
            - 🔍 Finds Input Package Numbers for tracking
            - 📦 Calculates cases needed (Quantity ÷ Units Per Case)
            - 📑 Generates formatted PDF reports (Portrait by default)
            - 🗂️ **Generate Separate PDFs** - one PDF per Sales Order, downloaded together as a single ZIP
            - 🎯 Filter by customer, order, or category
            - 📊 Data overview and analytics
            - 📋 Clean product-focused layout (Customer/SO columns optional)
            - 🗓️ Organized footer with generation time, customers, sales orders, and delivery dates
            - ✅ Auto-filters to Processing orders only
            
            **v1.3 Improvements:**
            - 🗂️ New "Generate Separate PDFs" button - splits the current filter into one PDF per Sales Order and delivers them in one ZIP, instead of generating and downloading each order by hand

            **v1.2.1 Improvements:**
            - ✨ Combined Qty/Cases into single column with Units prominent
            - 🔢 Smart decimal formatting (no unnecessary ".0")
            - ⚠️ Partial case highlighting with amber background
            - 📝 Proper singular/plural (1 Unit vs 2 Units, 1 Case vs 2 Cases)
            - 📐 Tighter, centered layout for Qty/Cases display

            ---
            *Folder icon on the "Generate Separate PDFs" button by [Flaticon](https://www.flaticon.com/).*
            """)
        
        with st.expander("📁 CSV File Requirements"):
            st.markdown("""
            **Sales Order Item History CSV:** *(Required)*
            - Auto-filters to Processing status only
            - Required columns: Customer, Order Number, Category, Product, Product Id, Package Batch Number, Package Label, Quantity, Status
            - Optional: Delivery Date (formatted as "Mon 9/29" in reports)
            
            **Assembly Data CSV:** *(Required)*  
            - Required columns: Input/Output, Package Number, Assembly Number
            - Both input and output records needed for proper linking
            
            **Product List CSV:** *(Optional)*
            - Required columns: ID, Units Per Case
            - Enables case quantity calculations (Quantity ÷ Units Per Case)
            
            *Sales Order and Assembly files: Tool auto-handles metadata lines and column mapping.*
            """)
    
    elif so_file and assembly_file:
        st.info("👈 Click the 'Process Data' button in the sidebar to analyze your files")
        if product_file:
            st.info("📦 Product List detected - cases will be calculated in the report")
        else:
            st.info("💡 Tip: Upload a Product List CSV to include calculated cases in your pick list")
        st.info("📋 Default: Portrait mode with product-focused layout (Customer/SO columns optional)")
    
    else:
        missing_files = []
        if not so_file:
            missing_files.append("Sales Order Item History")
        if not assembly_file:
            missing_files.append("Assembly Data")
        
        st.warning(f"📁 Please upload the {' and '.join(missing_files)} CSV file(s) to continue")
        if product_file and not (so_file and assembly_file):
            st.info("📦 Product List uploaded - add the other required files to process data")